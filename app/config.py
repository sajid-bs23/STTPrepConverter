from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from dotenv import load_dotenv
import os

# Explicitly load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # We still keep model_config for extra flexibility, 
    # but environment variables already loaded by load_dotenv() will take precedence.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 2

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Celery
    CELERY_CONCURRENCY: int = 4
    CELERY_MAX_TASKS_PER_CHILD: int = 50
    CELERY_TASK_SOFT_TIME_LIMIT: int = 7200
    CELERY_TASK_TIME_LIMIT: int = 7500

    # Storage
    TEMP_DIR: Path = Path("/tmp/converter")
    MAX_UPLOAD_SIZE_MB: int = 4096
    MIN_DISK_SPACE_GB: int = 10

    # Retry / Webhook
    WEBHOOK_MAX_RETRIES: int = 5
    WEBHOOK_RETRY_BACKOFF_BASE: int = 2
    UPLOAD_MAX_RETRIES: int = 3
    UPLOAD_RETRY_BACKOFF_BASE: int = 2

    # Cleanup
    TEMP_FILE_TTL_SECONDS: int = 3600

    # FFmpeg
    FFMPEG_BIN: str = "ffmpeg"

    # Security
    ALLOW_HTTP_CALLBACKS: bool = False
    ALLOW_PRIVATE_IPS: bool = False

settings = Settings()
