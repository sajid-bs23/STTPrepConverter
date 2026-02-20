# Video-to-Audio Converter Microservice (STTPrepConverter)

A high-performance, production-grade microservice designed to convert video files into optimized audio (16kHz mono Mp3)
for Speech-to-Text (STT) and transcription pipelines.

## 🚀 Features

- **Optimal Audio for AI:** Automatic highpass/lowpass filtering, silence removal, and volume normalization (
  `loudnorm`).
- **Scalable Architecture:** Built with **FastAPI**, **Celery**, and **Redis** for efficient asynchronous processing.
- **Large File Support:** Handles videos up to 4GB using streaming data paths to maintain a low memory footprint.
- **Safety First:**
    - **SSRF Protection:** Validates webhooks and upload URLs against internal/private IP ranges.
    - **Disk Guard:** Monitors storage capacity before accepting new jobs.
    - **Stream Validation:** Preflights files with `ffprobe` to ensure valid audio tracks exist.
- **Automated Lifecycle:** Self-cleaning temporary storage with periodic orphaned-file discovery.
- **Observability:** Structured JSON logging (`structlog`) and Prometheus metrics integration.

## 🛠 Tech Stack

- **Core:** Python 3.13+, FastAPI
- **Task Queue:** Celery 5.x + Redis 7
- **Media Engine:** FFmpeg
- **Infrastructure:** Docker & Docker Compose

## 📦 Getting Started

### Prerequisites

- Docker & Docker Compose
- FFmpeg (for local development without Docker)

### Installation

1. **Clone the repository:**
   ```bash
   git clone git@github.com:sajid-bs23/STTPrepConverter.git
   cd STTPrepConverter
   ```

2. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Edit .env to set your specific configurations
   ```

3. **Deploy with Docker Compose:**
   ```bash
   docker compose up -d --build
   ```

## 🔌 API Reference

### 1. Submit a Conversion Job

`POST /jobs`

Accepts a video file upload and enqueues it for conversion.

**Request:** `multipart/form-data`

| Field                 | Type          | Required | Description                                                            |
|-----------------------|---------------|----------|------------------------------------------------------------------------|
| `file`                | binary        | ✅        | The video file (Accepted MIME: `video/*`, `application/octet-stream`). |
| `output_url`          | string (URL)  | ✅        | Pre-authenticated URL for HTTP PUT upload of the resulting WAV.        |
| `output_auth_token`   | string        | ✅        | Bearer token for the `output_url`.                                     |
| `callback_url`        | string (URL)  | ❌        | Webhook URL for status updates (POST).                                 |
| `callback_auth_token` | string        | ❌        | Optional Bearer token for the callback.                                |
| `job_id`              | string (UUID) | ❌        | Optional custom ID for idempotency.                                    |

**Success Response (`202 Accepted`):**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "created_at": "2025-01-01T12:00:00Z"
}
```

---

### 2. Poll Job Status

`GET /jobs/{job_id}`

**Response (`200 OK`):**

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

---

### 3. Health Check

`GET /health`

Returns the operational status of the service and its dependencies.

**Response (`200 OK` or `503 Service Unavailable`):**

```json
{
  "status": "ok | error",
  "redis": "ok | error",
  "worker": "ok | error",
  "disk_free_gb": 15.4
}
```

---

## 🔄 Status State Machine

```
queued → processing → uploading → completed
                   ↘              ↗
                     failed (any stage)
```

## 📮 Testing with Postman

You can easily test the API using Postman. Follow these steps for the `POST /jobs` endpoint:

1. **Method & URL:** Set the method to `POST` and the URL to `http://localhost:8000/jobs`.
2. **Body:** Select `form-data`.
3. **Fields:**

    | Key                   | Type   | Value                                    |
    |-----------------------|--------|------------------------------------------|
    | `file`                | `File` | (Select your video file)                 |
    | `output_url`          | `Text` | `https://your-webhook-site.com/upload`   |
    | `output_auth_token`   | `Text` | `your-token`                             |
    | `callback_url`        | `Text` | `https://your-webhook-site.com/callback` |
    | `callback_auth_token` | `Text` | `your-callback-token` (Optional)         |
    | `job_id`              | `Text` | `custom-uuid` (Optional)                 |

4. **Headers:** Postman will automatically set the `Content-Type` to `multipart/form-data` with the correct boundary
   when you use the `form-data` body type.

> [!TIP]
> Use a service like [Webhook.site](https://webhook.site) to quickly generate test URLs for `output_url` and
`callback_url` to observe the service's out-bound requests.

### 🧪 Testing

The service includes local helper endpoints to simplify end-to-end testing without external webhook services:

- **Webhook Mock:** `POST /jobs/test-callback`
- **Upload Mock:** `PUT /jobs/test-upload`

You can use these as `callback_url` and `output_url` for local tests:

```bash
# Example end-to-end test using the mock endpoints
curl -X POST http://localhost:8000/jobs \
  -F "file=@input.mp4" \
  -F "output_url=http://api:8000/jobs/test-upload/output.mp3" \
  -F "output_auth_token=test" \
  -F "callback_url=http://api:8000/jobs/test-callback"
```

The service includes a comprehensive suite of unit tests. These are configured via `pytest.ini` and cover security,
storage, FFmpeg processing, and uploader services.

### Running Tests Locally

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the suite:**
   ```bash
   PYTHONPATH=. pytest
   ```

### Running Tests in Docker

You can also run tests inside the API container:

```bash
docker compose exec api pytest
```

## 📜 License

This project is licensed under the MIT License.



