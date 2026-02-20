import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from app.services import ffmpeg
from app.config import settings

@pytest.mark.asyncio
async def test_validate_audio_track_success():
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"0\n1", b""))
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        # Should not raise
        await ffmpeg.validate_audio_track(Path("dummy.mp4"))

@pytest.mark.asyncio
async def test_validate_audio_track_no_audio():
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b"")) # Empty output means no audio
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with pytest.raises(ffmpeg.NoAudioTrackError):
            await ffmpeg.validate_audio_track(Path("dummy.mp4"))

@pytest.mark.asyncio
async def test_convert_video_success(tmp_path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.wav"
    input_path.touch()
    
    mock_process = MagicMock()
    mock_process.returncode = 0
    # Mock stream reading
    mock_process.stdout.readline = AsyncMock(side_effect=[b"out_time_ms=1000000\n", b""])
    mock_process.stderr.read = AsyncMock(side_effect=[b"ffmpeg logs", b""])
    mock_process.wait = AsyncMock(return_value=0)
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        # We need to ensure output_path exists and has size > 0 for the check at the end
        output_path.write_text("dummy audio data")
        await ffmpeg.convert_video(input_path, output_path, "job-1")
