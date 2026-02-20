import httpx
import asyncio
import os
from pathlib import Path
from typing import Optional
from app.config import settings
from app.utils.logging import logger
from app.utils.security import is_safe_url
from app.utils.retry import retry_with_backoff

async def upload_output_wav(
    file_path: Path,
    output_url: str,
    auth_token: str,
    job_id: str
):
    """
    Uploads the resulting WAV file to the caller-supplied URL via HTTP PUT.
    Uses streaming to keep memory usage low.
    """
    # If the output_url doesn't look like it has a filename (e.g. doesn't end in .wav or similar),
    # and the user wants us to use the same filename, we append it.
    filename = file_path.name
    if not output_url.endswith(filename):
        # A simple way: if it doesn't end with a slash, add one
        if not output_url.endswith("/"):
            output_url += "/"
        output_url += filename

    if not is_safe_url(output_url):
        raise ValueError(f"Insecure output URL: {output_url}")

    async def do_upload():
        async def file_generator():
            # Run file reading in a thread pool to avoid blocking the event loop
            with open(file_path, "rb") as f:
                while True:
                    chunk = await asyncio.to_thread(f.read, 256 * 1024) # 256KB chunks
                    if not chunk:
                        break
                    yield chunk

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, write=600.0)) as client:
            response = await client.put(
                output_url,
                content=file_generator(),
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "audio/mpeg"
                }
            )
            response.raise_for_status()
            return response

    logger.info("upload_started", job_id=job_id, url=output_url)
    
    await retry_with_backoff(
        do_upload,
        max_retries=settings.UPLOAD_MAX_RETRIES,
        base_delay=settings.UPLOAD_RETRY_BACKOFF_BASE,
        exceptions=(httpx.HTTPStatusError, httpx.RequestError),
        job_id=job_id
    )
    
    logger.info("upload_completed", job_id=job_id)

async def fire_webhook(
    callback_url: str,
    job_id: str,
    status: str,
    error: Optional[str] = None,
    auth_token: Optional[str] = None
):
    """
    Sends a POST request to the callback URL with the final job status.
    Webhook failures do not fail the job.
    """
    if not is_safe_url(callback_url):
        logger.error("webhook_blocked_insecure_url", job_id=job_id, url=callback_url)
        return

    payload = {
        "job_id": job_id,
        "status": status,
        "error": error
    }
    
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    async def do_webhook():
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=10.0)) as client:
            response = await client.post(callback_url, json=payload, headers=headers)
            response.raise_for_status()
            return response

    logger.info("firing_webhook", job_id=job_id, url=callback_url, status=status)

    try:
        await retry_with_backoff(
            do_webhook,
            max_retries=settings.WEBHOOK_MAX_RETRIES,
            base_delay=settings.WEBHOOK_RETRY_BACKOFF_BASE,
            exceptions=(httpx.HTTPStatusError, httpx.RequestError),
            job_id=job_id
        )
        logger.info("webhook_delivered", job_id=job_id)
    except Exception as e:
        logger.error("webhook_failed_permanently", job_id=job_id, url=callback_url, error=str(e))
