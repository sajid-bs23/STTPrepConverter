import asyncio
from typing import Optional
from datetime import datetime
from pathlib import Path
from celery.exceptions import SoftTimeLimitExceeded
from app.worker.celery_app import celery_app
from app.services import storage, ffmpeg, uploader, redis_client
from app.utils.logging import logger
from app.config import settings

def run_async(coro):
    """Utility to run async coroutines from sync Celery worker."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    else:
        return asyncio.run(coro)

@celery_app.task(
    bind=True,
    name="converter.tasks.convert_video",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
    default_retry_delay=30,
)
def convert_video(self, job_id: str, output_url: str, output_auth_token: str, callback_url: Optional[str] = None, callback_auth_token: Optional[str] = None, original_filename: Optional[str] = None):
    """
    Main background task to convert video to WAV and upload it.
    """
    logger.info("task_received", job_id=job_id)
    
    # 1. Update status -> processing
    run_async(redis_client.update_job_status(job_id, "processing"))
    
    job_dir = storage.get_job_dir(job_id)
    # Find input file by pattern input.*
    input_files = list(job_dir.glob("input.*"))
    if not input_files:
        error_msg = "Input file not found."
        run_async(finish_job(job_id, "failed", error_msg, callback_url, callback_auth_token))
        return

    input_path = input_files[0]
    output_path = job_dir / "output.mp3"

    try:
        # 2. Validate audio track (ffprobe)
        run_async(ffmpeg.validate_audio_track(input_path))

        # 3. Run FFmpeg
        run_async(ffmpeg.convert_video(input_path, output_path, job_id))

        # 4. Update status -> uploading
        run_async(redis_client.update_job_status(job_id, "uploading"))

        # 5. Derive output filename (preserve base name)
        if original_filename:
            output_filename = Path(original_filename).with_suffix(".mp3").name
        else:
            output_filename = "output.mp3"
        
        output_path = job_dir / output_filename
        if output_path != job_dir / "output.mp3":
            # ffmpeg.convert_video used output.mp3, so we rename if needed
            (job_dir / "output.mp3").rename(output_path)

        # 6. Upload output WAV
        run_async(uploader.upload_output_wav(output_path, output_url, output_auth_token, job_id))

        # 6. Finish job -> completed
        run_async(finish_job(job_id, "completed", None, callback_url, callback_auth_token))

    except ffmpeg.NoAudioTrackError as e:
        run_async(finish_job(job_id, "failed", str(e), callback_url, callback_auth_token))
    except ffmpeg.FFmpegError as e:
        # Retry logic for FFmpeg errors
        if self.request.retries < self.max_retries:
            logger.warning("retrying_ffmpeg_task", job_id=job_id, attempt=self.request.retries + 1)
            raise self.retry(exc=e)
        else:
            run_async(finish_job(job_id, "failed", f"FFmpeg failed after retries: {str(e)}", callback_url, callback_auth_token))
    except SoftTimeLimitExceeded:
        run_async(finish_job(job_id, "failed", "Task timeout (SoftTimeLimitExceeded)", callback_url, callback_auth_token))
    except Exception as e:
        logger.exception("task_unexpected_error", job_id=job_id, error=str(e))
        run_async(finish_job(job_id, "failed", f"Unexpected error: {str(e)}", callback_url, callback_auth_token))
    finally:
        # 7. Clean up temp directory
        logger.info("cleanup_skipped_for_debugging", job_id=job_id)
        # storage.cleanup_job_dir(job_id)

async def finish_job(job_id: str, status: str, error: str = None, callback_url: str = None, callback_auth_token: str = None):
    """Updates Redis and fires the webhook."""
    await redis_client.update_job_status(job_id, status, error)
    if callback_url:
        await uploader.fire_webhook(callback_url, job_id, status, error, callback_auth_token)

@celery_app.task(name="converter.tasks.cleanup_orphaned_files")
def cleanup_orphaned_files():
    """
    Periodic task to clean up old job directories.
    Runs every 15 minutes (configured in beat).
    """
    if not settings.TEMP_DIR.exists():
        return

    logger.info("periodic_cleanup_started")
    now = datetime.utcnow().timestamp()
    
    for job_dir in settings.TEMP_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        
        # Check directory age
        mtime = job_dir.stat().st_mtime
        if (now - mtime) > settings.TEMP_FILE_TTL_SECONDS:
            job_id = job_dir.name
            # Verify job status in Redis
            # (Sync Redis client or run_async)
            job_data = run_async(redis_client.get_job(job_id))
            if not job_data or job_data.get("status") in ("completed", "failed"):
                logger.info("cleaning_orphaned_dir", job_id=job_id)
                storage.cleanup_job_dir(job_id)

# Celery Beat Schedule
celery_app.conf.beat_schedule = {
    "cleanup-every-30-mins": {
        "task": "converter.tasks.cleanup_orphaned_files",
        "schedule": 1800.0, # 30 minutes
    },
}
