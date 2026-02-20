import asyncio
import random
from typing import Callable, Any, Type, Tuple
from app.utils.logging import logger

async def retry_with_backoff(
    func: Callable,
    max_retries: int,
    base_delay: float,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    job_id: str = "unknown"
) -> Any:
    """
    Retries an async function with exponential backoff.
    delay = base_delay * (2 ** attempt) + jitter
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except exceptions as e:
            if attempt == max_retries - 1:
                logger.error("max_retries_reached", job_id=job_id, attempt=attempt, error=str(e))
                raise
            
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                "retrying_operation", 
                job_id=job_id, 
                attempt=attempt + 1, 
                max_retries=max_retries, 
                delay=f"{delay:.2f}s", 
                error=str(e)
            )
            await asyncio.sleep(delay)
