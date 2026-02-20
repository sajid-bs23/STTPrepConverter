import pytest
import os
import shutil
from pathlib import Path
from app.config import settings

@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Sets up a temporary test storage directory."""
    test_temp_dir = Path("/tmp/converter_test")
    test_temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Override settings for tests
    settings.TEMP_DIR = test_temp_dir
    settings.ALLOW_PRIVATE_IPS = True # Allow for local tests if needed, but normally False
    
    yield
    
    # Cleanup after all tests
    if test_temp_dir.exists():
        shutil.rmtree(test_temp_dir)

@pytest.fixture
def mock_job_id():
    return "test-job-123"

@pytest.fixture
def mock_job_dir(mock_job_id):
    job_dir = settings.TEMP_DIR / mock_job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    yield job_dir
    if job_dir.exists():
        shutil.rmtree(job_dir)
