# Video-to-Audio Converter Microservice — Requirements

> **Purpose of this document:** A complete, AI-coding-tool-friendly specification for building a production-grade
> video-to-audio conversion microservice. Follow every section in order. Do not skip constraints or error-handling rules.

---

## 1. Overview

A Python-based HTTP microservice that:

1. Accepts a video file upload (multipart) from an external caller.
2. Stores the file temporarily on local disk.
3. Enqueues a conversion job (Celery + Redis).
4. A Celery worker picks up the job, converts the video to a 16 kHz mono WAV using FFmpeg with audio-optimisation
   filters.
5. Uploads the resulting WAV to a caller-supplied URL (authenticated via a token provided at upload time).
6. Notifies the caller via a webhook/callback URL with the final job status.
7. Cleans up all temporary files regardless of outcome.

**Primary use-case:** Pre-processing long meeting recordings (minutes to hours) for downstream Speech-to-Text pipelines.

---

## 2. Tech Stack

| Layer                   | Choice                               | Notes                                          |
|-------------------------|--------------------------------------|------------------------------------------------|
| Language                | Python 3.13+                         |                                                |
| HTTP Framework          | FastAPI                              | Async, OpenAPI docs out of the box             |
| Task Queue              | Celery 5.x                           |                                                |
| Broker & Result Backend | Redis 7                              | Single Redis instance for both                 |
| Media Processing        | FFmpeg (system binary)               | Called via `subprocess` / `asyncio.subprocess` |
| Containerisation        | Docker + Docker Compose              |                                                |
| HTTP Client             | `httpx` (async)                      | Used for output upload & webhook delivery      |
| Temp Storage            | Local filesystem (`/tmp/converter/`) | Bind-mounted volume in Docker                  |

---

## 3. Repository Layout

```
converter-service/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── pyproject.toml          # or requirements.txt
├── app/
│   ├── main.py             # FastAPI app & lifespan
│   ├── config.py           # Settings via pydantic-settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py       # /jobs endpoints
│   │   └── schemas.py      # Pydantic request/response models
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── celery_app.py   # Celery instance & config
│   │   └── tasks.py        # convert_video task
│   ├── services/
│   │   ├── storage.py      # Temp file lifecycle helpers
│   │   ├── ffmpeg.py       # FFmpeg wrapper
│   │   └── uploader.py     # Output upload + webhook delivery
│   └── utils/
│       ├── logging.py
│       └── retry.py
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   └── test_tasks.py
└── scripts/
    └── healthcheck.sh
```

---

## 4. Configuration (`app/config.py`)

All config via environment variables (use `pydantic-settings`). Provide an `.env.example`.

```
# Server
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=2

# Redis
REDIS_URL=redis://redis:6379/0

# Celery
CELERY_CONCURRENCY=4              # Worker processes per container
CELERY_MAX_TASKS_PER_CHILD=50     # Restart worker after N tasks (memory safety)
CELERY_TASK_SOFT_TIME_LIMIT=7200  # 2 hours — SIGTERM to task
CELERY_TASK_TIME_LIMIT=7500       # 2 h 5 min — SIGKILL fallback

# Storage
TEMP_DIR=/tmp/converter
MAX_UPLOAD_SIZE_MB=4096           # 4 GB hard cap

# Retry / Webhook
WEBHOOK_MAX_RETRIES=5
WEBHOOK_RETRY_BACKOFF_BASE=2      # Exponential: 2^attempt seconds
UPLOAD_MAX_RETRIES=3
UPLOAD_RETRY_BACKOFF_BASE=2

# Cleanup
TEMP_FILE_TTL_SECONDS=3600        # Fallback sweep TTL for orphaned files

# FFmpeg
FFMPEG_BIN=ffmpeg
```

---

## 5. API Specification

### 5.1 `POST /jobs` — Submit a conversion job

**Request:** `multipart/form-data`

| Field                 | Type          | Required | Description                                                                            |
|-----------------------|---------------|----------|----------------------------------------------------------------------------------------|
| `file`                | binary        | ✅        | The video file to convert. Accepted MIME: `video/*`, `application/octet-stream`.       |
| `output_url`          | string (URL)  | ✅        | Pre-authenticated URL where the resulting WAV must be uploaded (HTTP PUT).             |
| `output_auth_token`   | string        | ✅        | Bearer token sent as `Authorization: Bearer <token>` header when uploading the output. |
| `callback_url`        | string (URL)  | ❌        | Webhook URL to receive a POST with the final job status.                               |
| `callback_auth_token` | string        | ❌        | Optional Bearer token for the callback URL.                                            |
| `job_id`              | string (UUID) | ❌        | Caller-supplied idempotency ID. If omitted, the service generates one.                 |

**Success Response `202 Accepted`:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "created_at": "2025-01-01T12:00:00Z"
}
```

**Validation errors:** `422 Unprocessable Entity` (FastAPI default schema validation).

**File too large:** `413 Request Entity Too Large`.

---

### 5.2 `GET /jobs/{job_id}` — Poll job status

**Response `200 OK`:**

```json
{
  "job_id": "550e8400-...",
  "status": "queued | processing | uploading | completed | failed",
  "created_at": "...",
  "started_at": "...",
  // null if not yet started
  "completed_at": "...",
  // null if not finished
  "error": null
  // string if failed
}
```

**Not found:** `404 Not Found`.

---

### 5.3 `GET /health` — Liveness probe

```json
{
  "status": "ok",
  "redis": "ok | error",
  "worker": "ok | error"
}
```

Returns `200` when healthy, `503` otherwise.

---

### 5.4 Status State Machine

```
queued → processing → uploading → completed
                   ↘              ↗
                     failed (any stage)
```

---

## 6. File Upload Handling

- Use FastAPI's `UploadFile` for streaming receive — **do not buffer the entire file in memory**.
- Stream directly to a temp file at `{TEMP_DIR}/{job_id}/input{ext}`.
- Preserve the original file extension (extract from `filename` field of the multipart).
- Enforce `MAX_UPLOAD_SIZE_MB`: track bytes written; if exceeded, delete partial file and return `413`.
- Detect MIME type from the first 512 bytes using `python-magic` as a secondary validation (warn but do not reject —
  some proxies strip MIME correctly).

---

## 7. Celery Task — `convert_video`

### 7.1 Task Signature

```python
@celery_app.task(
    bind=True,
    name="converter.tasks.convert_video",
    acks_late=True,  # Ack only after success/terminal failure
    reject_on_worker_lost=True,  # Requeue if worker crashes mid-task
    max_retries=3,
    default_retry_delay=30,
)
def convert_video(self, job_id: str): ...
```

### 7.2 Task Execution Steps

1. **Update status → `processing`** in Redis.
2. **Resolve paths:**
    - Input: `{TEMP_DIR}/{job_id}/input.*`
    - Output: `{TEMP_DIR}/{job_id}/output.wav`
3. **Run FFmpeg** (see §8). Capture `stdout` and `stderr`.
4. **On FFmpeg failure:**
    - If `self.request.retries < max_retries`: retry with exponential backoff.
    - If retries exhausted: update status → `failed`, fire webhook, clean up, raise.
5. **Update status → `uploading`**.
6. **Upload output WAV** to `output_url` (see §9.1).
7. **Update status → `completed`**.
8. **Fire success webhook** (see §9.2).
9. **Clean up temp directory** `{TEMP_DIR}/{job_id}/`.

### 7.3 Task Failure & Retry Rules

| Failure Type                             | Action                                                                                |
|------------------------------------------|---------------------------------------------------------------------------------------|
| FFmpeg non-zero exit                     | Retry up to 3× with 30 s backoff, then `failed`                                       |
| FFmpeg timeout (`SoftTimeLimitExceeded`) | Mark `failed`, clean up, fire webhook                                                 |
| Output upload failure                    | Retry upload up to `UPLOAD_MAX_RETRIES` independently before marking `failed`         |
| Webhook delivery failure                 | Retry webhook up to `WEBHOOK_MAX_RETRIES`; **do not** fail the job for webhook errors |
| Worker killed (OOM/crash)                | `reject_on_worker_lost=True` causes automatic requeue                                 |

---

## 8. FFmpeg Processing

### 8.1 Command Template

```bash
ffmpeg -y \
  -i {input_path} \
  -vn \
  -af "highpass=f=100,lowpass=f=8000,\
silenceremove=start_periods=1:start_duration=1:start_threshold=-45dB:\
stop_periods=-1:stop_duration=1:stop_threshold=-45dB,\
loudnorm" \
  -ac 1 \
  -ar 16000 \
  -c:a pcm_s16le \
  {output_path}
```

### 8.2 Implementation Rules

- Execute via `subprocess.Popen` (not `os.system`).
- Pass `-progress pipe:1` to capture real-time progress from `stdout`; parse `out_time_ms` to emit progress logs.
- Redirect `stderr` to a log file `{TEMP_DIR}/{job_id}/ffmpeg.log` for post-mortem debugging.
- Use `CELERY_TASK_SOFT_TIME_LIMIT` to interrupt the process cleanly (`SIGTERM` on the subprocess then `SIGKILL` after 5
  s).
- **Never** pass user-controlled strings directly into the shell command — use a list-form `args` to prevent injection.
- Validate the output file exists and has `size > 0` after FFmpeg exits successfully.

### 8.3 Large File Considerations

- FFmpeg processes files in a streaming fashion by default — no special chunking needed.
- Ensure the Docker volume for `TEMP_DIR` has sufficient space (document recommended: ≥ 2× the max expected file size).
- Set `ulimit -n 65536` in the worker container to handle large file descriptors.

---

## 9. Output Upload & Webhook

### 9.1 Output File Upload

- HTTP `PUT` to `output_url`.
- Headers: `Authorization: Bearer {output_auth_token}`, `Content-Type: audio/wav`.
- Stream the file using `httpx.AsyncClient` with `content=open(path, 'rb')` — **do not load into memory**.
- Retry logic: up to `UPLOAD_MAX_RETRIES`, exponential backoff (`2^attempt` seconds), retry on `5xx` and network errors
  only. Do **not** retry `4xx` (auth/URL errors are terminal).
- Timeout: connect 10 s, read 300 s (large files).

### 9.2 Webhook Callback

Fire a `POST` to `callback_url` with:

```json
{
  "job_id": "550e8400-...",
  "status": "completed | failed",
  "completed_at": "2025-01-01T12:05:00Z",
  "error": null
}
```

- Headers: `Content-Type: application/json`; if `callback_auth_token` provided:
  `Authorization: Bearer {callback_auth_token}`.
- Retry: up to `WEBHOOK_MAX_RETRIES`, exponential backoff, retry on `5xx` and network errors. Log permanently on
  failure — **never fail the job based on webhook result**.
- Timeout: connect 5 s, read 10 s.

---

## 10. Temporary Storage Lifecycle

- Every job's files live under `{TEMP_DIR}/{job_id}/`.
- **Happy path:** temp dir deleted at end of `convert_video` task, inside a `finally` block.
- **Fallback sweep:** A Celery `beat` periodic task (`cleanup_orphaned_files`) runs every 15 minutes and deletes any
  `{TEMP_DIR}/*` directories older than `TEMP_FILE_TTL_SECONDS` whose job status is `completed` or `failed`.
- On API startup, validate that `TEMP_DIR` is writable; fail fast if not.

---

## 11. Job State Storage in Redis

Use Redis directly (via `redis-py`) for job metadata. **Do not use Celery's result backend** for job metadata — it has
TTL and visibility limitations.

### Key Schema

```
job:{job_id}     → Redis Hash
  status         : queued | processing | uploading | completed | failed
  created_at     : ISO8601 string
  started_at     : ISO8601 string or ""
  completed_at   : ISO8601 string or ""
  error          : error message string or ""
  input_path     : absolute path on disk
```

- Set TTL of 7 days (`604800` seconds) on each `job:{job_id}` key after terminal state is reached.
- Use `SETNX` / `SET NX` when creating the job key to enforce idempotency on caller-supplied `job_id`.

---

## 12. Queue & Concurrency Design

### Celery Configuration

```python
# celery_app.py
app = Celery("converter")
app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # Critical: don't pre-fetch multiple long tasks
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=settings.CELERY_MAX_TASKS_PER_CHILD,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    broker_transport_options={"visibility_timeout": 8000},  # Must be > task_time_limit
)
```

### Scaling

- `CELERY_CONCURRENCY` controls parallel conversions per worker container.
- Horizontal scaling: run multiple `worker` containers (all connect to same Redis). Docker Compose `--scale worker=N`.
- Recommended starting point: 1 worker process per 2 CPU cores, capped by available disk I/O.

### Queue Priority (optional, implement if needed)

Define two queues: `high` (short files < 10 min) and `default` (everything else). Route based on file size detected at
upload time.

---

## 13. Docker Compose

```yaml
# docker-compose.yml (structure — fill in exact values)
version: "3.9"
services:

  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - temp_storage:/tmp/converter
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: [ "CMD", "curl", "-f", "http://localhost:8000/health" ]
      interval: 30s
      timeout: 5s
      retries: 3

  worker:
    build: .
    command: celery -A app.worker.celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY}
    env_file: .env
    volumes:
      - temp_storage:/tmp/converter
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: "2G"
    # Scale with: docker compose up --scale worker=3

  beat:
    build: .
    command: celery -A app.worker.celery_app beat --loglevel=info
    env_file: .env
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    healthcheck:
      test: [ "CMD", "redis-cli", "ping" ]
      interval: 10s
      timeout: 3s
      retries: 5
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes   # Persist queue on restart

volumes:
  temp_storage:
  redis_data:
```

### Dockerfile Requirements

- Base image: `python:3.13-slim`
- Install `ffmpeg` via `apt-get` in the same layer as other system deps.
- Use a non-root user (`appuser`).
- Copy and install Python deps before copying source (layer cache efficiency).
- `WORKDIR /app`

---

## 14. Observability & Logging

- Use Python `structlog` for structured JSON logging throughout.
- Log at every state transition, FFmpeg progress milestone (every 10%), upload start/end, webhook delivery attempt.
- Include `job_id` in every log line as a structured field.
- **Do not log `output_auth_token` or `callback_auth_token`** — mask them as `***`.
- Expose a `/metrics` endpoint (Prometheus format) using `prometheus-fastapi-instrumentator`. Key metrics:
    - `converter_jobs_total{status}` — counter
    - `converter_job_duration_seconds` — histogram
    - `converter_queue_depth` — gauge (query Redis)
    - `converter_ffmpeg_duration_seconds` — histogram

---

## 15. Security

- Validate `output_url` and `callback_url` are `https://` (reject `http://` in production; configurable via
  `ALLOW_HTTP_CALLBACKS=false`).
- Validate URL hostnames are not RFC-1918 private addresses (SSRF protection) — use `ipaddress` stdlib.
- Tokens are stored only in Redis job hash with TTL. Never logged.
- The API itself does **not** require authentication (it is an internal microservice; mTLS or network policy handles
  perimeter auth). Add `API_KEY` env var as optional bearer-token gate if needed.
- FFmpeg is invoked via list-form `args` — no shell interpolation of user input.
- `MAX_UPLOAD_SIZE_MB` enforced before writing to disk to prevent disk exhaustion.

---

## 16. Error Handling Matrix

| Scenario                    | HTTP Response            | Celery Behaviour                         | Webhook Fired?      |
|-----------------------------|--------------------------|------------------------------------------|---------------------|
| File exceeds size limit     | `413`                    | Job not created                          | No                  |
| Invalid URL format          | `422`                    | Job not created                          | No                  |
| Redis unavailable at submit | `503`                    | —                                        | No                  |
| FFmpeg exits non-zero       | `202` (already accepted) | Retry × 3, then `failed`                 | Yes (failed)        |
| FFmpeg timeout              | `202`                    | Immediate `failed`, no retry             | Yes (failed)        |
| Output upload 4xx           | `202`                    | Terminal `failed`                        | Yes (failed)        |
| Output upload 5xx / network | `202`                    | Retry upload × 3, then `failed`          | Yes (failed)        |
| Webhook 5xx / network       | `202`                    | Retry webhook × 5, log, continue         | —                   |
| Worker OOM crash            | `202`                    | Auto-requeue via `reject_on_worker_lost` | No (until complete) |
| Disk full during convert    | `202`                    | `failed` with error message              | Yes (failed)        |

---

## 17. Testing Requirements

- **Unit tests** (`pytest`): FFmpeg wrapper, uploader retry logic, webhook delivery, state machine transitions. Mock
  `subprocess` and `httpx`.
- **Integration tests**: Spin up Redis in Docker (use `pytest-docker` or `testcontainers`). Submit real job payloads;
  assert status transitions.
- **Load test** (optional, `locust`): Simulate 10 concurrent uploads of 500 MB files; assert no job losses.
- Minimum 80% code coverage.

---

## 18. Refined Edge Cases & Resolutions

The following edge cases were identified and resolved during the planning and implementation phase:

| ID        | Edge Case              | Resolution                                                                                                                                        |
|-----------|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| **EC-01** | **Disk Exhaustion**    | Added `MIN_DISK_SPACE_GB` check in API (`POST /jobs`) and Health endpoint. Fails fast if space is insufficient.                                   |
| **EC-02** | **No Audio Track**     | Added `ffprobe` validation step in `convert_video` task. Jobs with no audio streams are marked `failed` immediately.                              |
| **EC-03** | **SSRF Attacks**       | Implemented URL validation in `uploader.py` using `ipaddress` to block internal/private/loopback ranges for `output_url` and `callback_url`.      |
| **EC-04** | **Orphaned Files**     | Added `boot_cleanup` to lifespan events to wipe temp storage on startup. Periodic 15-min sweep handles cleanup of completed/failed job leftovers. |
| **EC-05** | **Idempotency**        | Uses `SET NX` in Redis. If a `job_id` is reused, the service returns the existing job's status instead of creating a new one.                     |
| **EC-06** | **Large File Uploads** | Streaming upload implementation with a hard byte-count cap (`MAX_UPLOAD_SIZE_MB`) during the write process to prevent OOM and disk filling.       |

---

## 19. Implementation Order (Recommended for AI Coding Agents)

Follow this sequence to avoid circular dependency issues:

1. `app/config.py` — Settings model.
2. `app/utils/logging.py` — Structured logger setup.
3. `app/worker/celery_app.py` — Celery instance (no tasks yet).
4. `app/services/storage.py` — Temp dir helpers.
5. `app/services/ffmpeg.py` — FFmpeg subprocess wrapper + tests.
6. `app/services/uploader.py` — Upload + webhook with retry + tests.
7. `app/worker/tasks.py` — `convert_video` task wiring steps 1–9.
8. `app/api/schemas.py` — Pydantic models.
9. `app/api/routes.py` — FastAPI routes.
10. `app/main.py` — App factory + lifespan.
11. `Dockerfile` + `docker-compose.yml`.
12. `tests/` — Fill out unit and integration tests.

---

## 19. Out of Scope (for this service)

- STT / transcription — downstream concern.
- Long-term storage of audio files — caller's responsibility via `output_url`.
- Authentication of the API itself — handled at infrastructure level.
- Resumable/chunked uploads from the video source — future enhancement if needed.

---

*End of requirements document.*
