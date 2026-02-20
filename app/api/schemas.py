from pydantic import BaseModel, HttpUrl, Field
from typing import Optional
from datetime import datetime
import uuid

class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    redis: str
    worker: str
    disk_free_gb: float
