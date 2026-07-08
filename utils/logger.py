import sys
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("pipeline.log", rotation="10 MB", level="DEBUG")

def get_logger(name: str):
    return logger.bind(name=name)
