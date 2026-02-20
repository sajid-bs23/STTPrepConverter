from fastapi import FastAPI
from contextlib import asynccontextmanager
from prometheus_fastapi_instrumentator import Instrumentator
from app.api.routes import router as jobs_router, health_router
from app.services import storage, redis_client
from app.utils.logging import logger, setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    logger.info("service_starting")
    
    # 1. Validate storage
    if not storage.validate_temp_dir():
        logger.critical("storage_initialization_failed")
        # In a real production app, we might want to exit here, 
        # but for a containerized app, failing health checks will suffice.
    
    # 2. Boot Cleanup
    storage.boot_cleanup()
    
    # 3. Initialize Redis
    redis_client.get_redis_client()
    
    yield
    
    # Shutdown
    logger.info("service_shutting_down")
    await redis_client.close_redis()

app = FastAPI(
    title="Video-to-Audio Converter Microservice",
    description="Optimizes meeting recordings for STT pipelines.",
    version="0.1.0",
    lifespan=lifespan
)

# Instrument for Prometheus metrics
Instrumentator().instrument(app).expose(app)

# Include Routers
app.include_router(jobs_router)
app.include_router(health_router)

@app.get("/")
async def root():
    return {"message": "Video-to-Audio Converter Microservice is running. See /docs for API documentation."}
