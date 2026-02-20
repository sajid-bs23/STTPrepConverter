from celery import Celery
from app.config import settings

celery_app = Celery("converter")

celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=settings.CELERY_MAX_TASKS_PER_CHILD,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    broker_transport_options={"visibility_timeout": 8000}, # Must be > task_time_limit
    timezone="UTC",
)

# Discover tasks
celery_app.autodiscover_tasks(["app.worker"])
