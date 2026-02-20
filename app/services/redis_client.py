from redis.asyncio import Redis
from app.config import settings
import json
from datetime import datetime
from typing import Optional, Dict, Any

# Async Redis client for API
_redis: Optional[Redis] = None
_last_loop = None

def get_redis_client() -> Redis:
    global _redis, _last_loop
    try:
        import asyncio
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    # If the loop has changed (common in Celery workers using asyncio.run),
    # we must re-initialize the client.
    if _redis is None or current_loop != _last_loop:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        _last_loop = current_loop
    
    return _redis

async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None

# Job state management helpers (Redis Hashes)
async def create_job(job_id: str, input_path: str):
    client = get_redis_client()
    job_key = f"job:{job_id}"
    data = {
        "status": "queued",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "started_at": "",
        "completed_at": "",
        "error": "",
        "input_path": input_path
    }
    # SET NX to enforce idempotency
    return await client.hset(job_key, mapping=data)

async def update_job_status(job_id: str, status: str, error: Optional[str] = None):
    client = get_redis_client()
    job_key = f"job:{job_id}"
    updates = {"status": status}
    
    if status == "processing" and not await client.hget(job_key, "started_at"):
        updates["started_at"] = datetime.utcnow().isoformat() + "Z"
    
    if status in ("completed", "failed"):
        updates["completed_at"] = datetime.utcnow().isoformat() + "Z"
        if error:
            updates["error"] = error
        # Set expiry for terminal states
        await client.expire(job_key, 604800) # 7 days
    
    await client.hset(job_key, mapping=updates)

async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    client = get_redis_client()
    job_key = f"job:{job_id}"
    data = await client.hgetall(job_key)
    return data if data else None
