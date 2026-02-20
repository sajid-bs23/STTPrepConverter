import shutil
import os
from pathlib import Path
from app.config import settings
from app.utils.logging import logger

def get_job_dir(job_id: str) -> Path:
    """Returns the absolute path to the job's temporary directory."""
    return settings.TEMP_DIR / job_id

def create_job_dir(job_id: str) -> Path:
    """Creates the job's temporary directory if it doesn't exist."""
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir

def cleanup_job_dir(job_id: str):
    """Deletes the job's temporary directory and all its contents."""
    job_dir = get_job_dir(job_id)
    if job_dir.exists():
        try:
            shutil.rmtree(job_dir)
            logger.info("cleaned_up_job_dir", job_id=job_id, path=str(job_dir))
        except Exception as e:
            logger.error("cleanup_failed", job_id=job_id, error=str(e))

def check_disk_space() -> bool:
    """
    Checks if the available disk space in TEMP_DIR is above the threshold.
    Returns True if healthy, False otherwise.
    """
    try:
        total, used, free = shutil.disk_usage(settings.TEMP_DIR.parent if not settings.TEMP_DIR.exists() else settings.TEMP_DIR)
        free_gb = free / (1024**3)
        is_healthy = free_gb >= settings.MIN_DISK_SPACE_GB
        if not is_healthy:
            logger.warning("low_disk_space", available_gb=free_gb, threshold_gb=settings.MIN_DISK_SPACE_GB)
        return is_healthy
    except Exception as e:
        logger.error("disk_check_failed", error=str(e))
        return False

def boot_cleanup():
    """Wipes the TEMP_DIR on service startup to ensure a clean slate."""
    if settings.TEMP_DIR.exists():
        logger.info("boot_cleanup_started", path=str(settings.TEMP_DIR))
        try:
            # Delete children but keep the TEMP_DIR itself
            for item in settings.TEMP_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            logger.info("boot_cleanup_completed")
        except Exception as e:
            logger.error("boot_cleanup_failed", error=str(e))
    else:
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("temp_dir_created", path=str(settings.TEMP_DIR))

def validate_temp_dir():
    """Ensures TEMP_DIR is writable on startup."""
    try:
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        test_file = settings.TEMP_DIR / ".write_test"
        test_file.touch()
        test_file.unlink()
        return True
    except Exception as e:
        logger.critical("temp_dir_not_writable", path=str(settings.TEMP_DIR), error=str(e))
        return False
