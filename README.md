# Media-to-Audio Converter Microservice (STTPrepConverter)

A high-performance, production-grade microservice designed to convert **video or audio files** into optimized MP3
(16 kHz mono) for Speech-to-Text (STT) and transcription pipelines.

## 🚀 Features

- **Universal Media Input:** Accepts any video (`mp4`, `mkv`, `mov`, `webm`, …) or audio (`mp3`, `wav`, `ogg`, `flac`,
  `m4a`, …) file supported by FFmpeg.
- **STT-Optimized Output:** Outputs a 16 kHz mono MP3 with automatic highpass/lowpass filtering, silence removal, and
  loudness normalization (`loudnorm`).
- **Scalable Architecture:** Built with **FastAPI**, **Celery**, and **Redis** for efficient asynchronous processing.
- **Large File Support:** Handles files up to 4 GB using streaming data paths to maintain a low memory footprint.
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

Accepts a video or audio file and enqueues it for STT-optimized MP3 conversion.

**Request:** `multipart/form-data`

| Field                 | Type          | Required | Description                                                                                                        |
|-----------------------|---------------|----------|--------------------------------------------------------------------------------------------------------------------|
| `file`                | binary        | ✅        | The media file to convert. Accepted: any video or audio format (`video/*`, `audio/*`, `application/octet-stream`). |
| `output_url`          | string (URL)  | ✅        | Pre-authenticated URL for HTTP PUT upload of the resulting MP3.                                                    |
| `output_auth_token`   | string        | ✅        | Bearer token for the `output_url`.                                                                                 |
| `callback_url`        | string (URL)  | ❌        | Webhook URL for status updates (POST).                                                                             |
| `callback_auth_token` | string        | ❌        | Optional Bearer token for the callback.                                                                            |
| `job_id`              | string (UUID) | ❌        | Optional custom ID for idempotency.                                                                                |

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
  "completed_at": "...",
  "error": null
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

1. **Method & URL:** Set the method to `POST` and the URL to `http://localhost:8000/jobs`.
2. **Body:** Select `form-data`.
3. **Fields:**

| Key                   | Type   | Value                                                 |
|-----------------------|--------|-------------------------------------------------------|
| `file`                | `File` | Select a video **or** audio file                      |
| `output_url`          | `Text` | `http://localhost:8000/jobs/test-upload/output.mp3`   |
| `output_auth_token`   | `Text` | `test`                                                |
| `callback_url`        | `Text` | `http://localhost:8000/jobs/test-callback` (Optional) |
| `callback_auth_token` | `Text` | `your-callback-token` (Optional)                      |
| `job_id`              | `Text` | `custom-uuid` (Optional)                              |

> [!TIP]
> Use a service like [Webhook.site](https://webhook.site) to quickly generate test URLs for `output_url` and
`callback_url` to observe the service's outbound requests.

### 🧪 Local Helper Endpoints

The service includes mock endpoints to simplify end-to-end testing without external services:

- **Webhook Mock:** `POST /jobs/test-callback`
- **Upload Mock:** `PUT /jobs/test-upload/{filename}`

**Example — submit a video file:**

```bash
curl -X POST http://localhost:8000/jobs \
  -F "file=@input.mp4" \
  -F "output_url=http://api:8000/jobs/test-upload/output.mp3" \
  -F "output_auth_token=test" \
  -F "callback_url=http://api:8000/jobs/test-callback"
```

**Example — submit an audio file:**

```bash
curl -X POST http://localhost:8000/jobs \
  -F "file=@recording.wav" \
  -F "output_url=http://api:8000/jobs/test-upload/recording.mp3" \
  -F "output_auth_token=test" \
  -F "callback_url=http://api:8000/jobs/test-callback"
```

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

```bash
docker compose exec api pytest
```

## 📜 License

This project is licensed under the MIT License.
