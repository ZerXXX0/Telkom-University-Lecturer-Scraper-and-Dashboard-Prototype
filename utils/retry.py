from tenacity import retry, stop_after_attempt, wait_exponential
from utils.logger import get_logger

logger = get_logger("retry")

def with_retry(max_attempts=3, min_wait=2, max_wait=10):
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        reraise=True
    )
