from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Depends
from typing import Optional
import uuid
import os
import shutil
from datetime import datetime
from app.api.schemas import JobCreateResponse, JobStatusResponse, HealthResponse
from app.services import storage, redis_client
from app.worker.tasks import convert_video
from app.config import settings
from app.utils.logging import logger

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.post("", response_model=JobCreateResponse, status_code=202)
async def create_job_endpoint(
    file: UploadFile = File(...),
    output_url: str = Form(...),
    output_auth_token: str = Form(...),
    callback_url: Optional[str] = Form(None),
    callback_auth_token: Optional[str] = Form(None),
    job_id: Optional[str] = Form(None)
):
    # 1. Disk Space Check
    if not storage.check_disk_space():
        raise HTTPException(status_code=503, detail="Service unavailable: Low disk space.")

    # 2. Idempotency / Job ID generation
    if not job_id:
        job_id = str(uuid.uuid4())
    
    # Check if job already exists in Redis
    existing_job = await redis_client.get_job(job_id)
    if existing_job:
        logger.info("job_already_exists", job_id=job_id)
        return JobCreateResponse(
            job_id=job_id,
            status=existing_job["status"],
            created_at=datetime.fromisoformat(existing_job["created_at"].replace("Z", ""))
        )

    # 3. File Size Validation (Soft check on header)
    # The actual enforcement happens during streaming in main.py or middleware if we used one,
    # but let's do it here while saving.
    
    job_dir = storage.create_job_dir(job_id)
    ext = os.path.splitext(file.filename)[1] if file.filename else ".bin"
    input_path = job_dir / f"input{ext}"
    
    # 4. Stream file to disk
    try:
        content_length = 0
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        
        with open(input_path, "wb") as f:
            while chunk := await file.read(1024 * 1024): # 1MB chunks
                content_length += len(chunk)
                if content_length > max_bytes:
                    f.close()
                    storage.cleanup_job_dir(job_id)
                    raise HTTPException(status_code=413, detail=f"File exceeds limit of {settings.MAX_UPLOAD_SIZE_MB}MB")
                f.write(chunk)
        
        logger.info("file_uploaded_successfully", job_id=job_id, path=str(input_path), size=content_length)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("file_save_failed", job_id=job_id, error=str(e))
        storage.cleanup_job_dir(job_id)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    # 5. Create Job in Redis
    await redis_client.create_job(job_id, str(input_path))

    # 6. Enqueue Celery Task
    original_filename = file.filename or "input.bin"
    convert_video.delay(
        job_id=job_id,
        output_url=output_url,
        output_auth_token=output_auth_token,
        callback_url=callback_url,
        callback_auth_token=callback_auth_token,
        original_filename=original_filename
    )

    return JobCreateResponse(
        job_id=job_id,
        status="queued",
        created_at=datetime.utcnow()
    )

@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job_data = await redis_client.get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    def parse_dt(dt_str):
        return datetime.fromisoformat(dt_str.replace("Z", "")) if dt_str else None

    return JobStatusResponse(
        job_id=job_id,
        status=job_data["status"],
        created_at=parse_dt(job_data["created_at"]),
        started_at=parse_dt(job_data["started_at"]),
        completed_at=parse_dt(job_data["completed_at"]),
        error=job_data.get("error") if job_data.get("error") else None
    )

health_router = APIRouter(tags=["health"])

@health_router.get("/health", response_model=HealthResponse)
async def health_check():
    # Simple check for Redis
    redis_ok = "ok"
    try:
        await redis_client.get_redis_client().ping()
    except:
        redis_ok = "error"
    
    # Check for free disk
    total, used, free = shutil.disk_usage(settings.TEMP_DIR.parent)
    free_gb = free / (1024**3)
    
    # Worker check is harder to do reliably without overhead, 
    # but we can check if any workers are online via celery inspection if needed.
    # For now, let's just say "ok" if we can reach redis which serves as the broker.
    worker_ok = "ok" if redis_ok == "ok" else "error"

    status_code = 200 if redis_ok == "ok" else 503
    
    # Return 503 if disk is critically low (less than threshold)
    if free_gb < settings.MIN_DISK_SPACE_GB:
        status_code = 503

    from fastapi import Response
    import json
    content = {
        "status": "ok" if status_code == 200 else "error",
        "redis": redis_ok,
        "worker": worker_ok,
        "disk_free_gb": round(free_gb, 2)
    }
    return content # FastAPI handles response_model and status_code if we didn't override


# Test helper routes (not for production)
@router.post("/test-callback")
async def test_callback_post(request: Request):
    """Mock webhook receiver for status updates."""
    payload = await request.json()
    auth = request.headers.get("Authorization")
    logger.info("test_callback_received", payload=payload, auth=auth)
    return {"status": "received", "type": "webhook"}

@router.put("/test-upload/{filename}")
async def test_upload_put(request: Request, filename: str):
    """Mock output storage for file uploads."""
    content = await request.body()
    
    # Save to the temp directory for verification
    test_file_path = settings.TEMP_DIR / filename
    settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(test_file_path, "wb") as f:
        f.write(content)
        
    auth = request.headers.get("Authorization")
    logger.info("test_upload_received", size=len(content), auth=auth, saved_to=str(test_file_path))
    return {"status": "uploaded", "size": len(content), "saved_to": str(test_file_path)}
