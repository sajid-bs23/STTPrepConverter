import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from app.services import uploader

@pytest.mark.asyncio
async def test_upload_output_wav_success(tmp_path):
    file_path = tmp_path / "output.wav"
    file_path.touch()
    
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient.put", return_value=mock_response) as mock_put:
        with patch("app.services.uploader.is_safe_url", return_value=True):
            await uploader.upload_output_wav(file_path, "https://public.com/upload", "token", "job-1")
            assert mock_put.called

@pytest.mark.asyncio
async def test_fire_webhook_success():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
        with patch("app.services.uploader.is_safe_url", return_value=True):
            await uploader.fire_webhook("https://public.com/cb", "job-1", "completed")
            assert mock_post.called

@pytest.mark.asyncio
async def test_fire_webhook_insecure():
    with patch("app.services.uploader.is_safe_url", return_value=False):
        # Should log error and return early without calling httpx
        with patch("httpx.AsyncClient.post") as mock_post:
            await uploader.fire_webhook("http://internal/cb", "job-1", "completed")
            assert not mock_post.called
