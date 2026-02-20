import pytest
import os
from app.services import storage
from app.config import settings

def test_job_dir_lifecycle(mock_job_id):
    job_dir = storage.get_job_dir(mock_job_id)
    assert not job_dir.exists()
    
    storage.create_job_dir(mock_job_id)
    assert job_dir.exists()
    assert job_dir.is_dir()
    
    storage.cleanup_job_dir(mock_job_id)
    assert not job_dir.exists()

def test_boot_cleanup(mock_job_id):
    # Create some dummy files
    storage.create_job_dir(mock_job_id)
    dummy_file = settings.TEMP_DIR / "orphaned.txt"
    dummy_file.touch()
    
    assert (settings.TEMP_DIR / mock_job_id).exists()
    assert dummy_file.exists()
    
    storage.boot_cleanup()
    
    assert not (settings.TEMP_DIR / mock_job_id).exists()
    assert not dummy_file.exists()
    assert settings.TEMP_DIR.exists() # Base dir should stay

def test_check_disk_space():
    # Should be true on most systems during test
    assert storage.check_disk_space() is True
