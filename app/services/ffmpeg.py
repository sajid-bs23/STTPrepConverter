import asyncio
import re
import os
from pathlib import Path
from typing import Optional, Callable, Dict
from app.config import settings
from app.utils.logging import logger

class FFmpegError(Exception):
    pass

class NoAudioTrackError(FFmpegError):
    pass

async def validate_audio_track(input_path: Path):
    """
    Uses ffprobe to check if the input file contains at least one audio stream.
    Raises NoAudioTrackError if none found.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(input_path)
    ]
    
    logger.info("validating_audio_track", path=str(input_path))
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        logger.error("ffprobe_failed", error=stderr.decode().strip())
        raise FFmpegError(f"ffprobe failed: {stderr.decode().strip()}")
    
    if not stdout.strip():
        logger.warning("no_audio_track_found", path=str(input_path))
        raise NoAudioTrackError(f"No audio track found in {input_path.name}")
    
    logger.info("audio_track_validated", streams=stdout.decode().strip().split('\n'))

async def convert_video(
    input_path: Path,
    output_path: Path,
    job_id: str,
    on_progress: Optional[Callable[[float], None]] = None
):
    """
    Converts video to 16kHz mono WAV using FFmpeg with audio optimization filters.
    Parses execution progress from stdout.
    """
    # Optimized filter chain for STT
    audio_filters = (
        "highpass=f=100,"
        "lowpass=f=8000,"
        "silenceremove=start_periods=1:start_duration=1:start_threshold=-45dB:"
        "stop_periods=-1:stop_duration=1:stop_threshold=-45dB,"
        "loudnorm"
    )

    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-i", str(input_path),
        "-vn",
        "-af", audio_filters,
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        "-progress", "pipe:1",
        str(output_path)
    ]

    logger.info("ffmpeg_started", job_id=job_id, cmd=" ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # Regex to parse FFmpeg progress
    # We look for out_time_ms=...
    # But since we don't know the total duration easily without another ffprobe call,
    # we'll just log milestones or use percentage if we had total duration.
    # For now, let's just parse milestones by time if possible, or just emit raw time.
    
    async def log_output(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            line_str = line.decode().strip()
            if "out_time_ms=" in line_str:
                try:
                    time_ms = int(line_str.split('=')[1])
                    # Every 10 seconds of output, log a milestone
                    if time_ms % 10000000 < 500000: # Rough approximation
                         logger.info("ffmpeg_progress", job_id=job_id, time_ms=time_ms)
                except:
                    pass

    # We also want to capture stderr to a log file for debugging
    log_file_path = output_path.parent / "ffmpeg.log"
    
    async def capture_stderr(stream):
        with open(log_file_path, "wb") as f:
            while True:
                chunk = await stream.read(1024)
                if not chunk:
                    break
                f.write(chunk)

    try:
        await asyncio.gather(
            log_output(process.stdout),
            capture_stderr(process.stderr)
        )
        await process.wait()
    except asyncio.CancelledError:
        process.terminate()
        await process.wait()
        raise

    if process.returncode != 0:
        logger.error("ffmpeg_failed", job_id=job_id, returncode=process.returncode)
        raise FFmpegError(f"FFmpeg failed with exit code {process.returncode}. See {log_file_path} for details.")

    if not output_path.exists() or output_path.stat().st_size == 0:
        logger.error("ffmpeg_output_invalid", job_id=job_id)
        raise FFmpegError("FFmpeg produced empty or missing output file.")

    logger.info("ffmpeg_completed", job_id=job_id, output_size=output_path.stat().st_size)
