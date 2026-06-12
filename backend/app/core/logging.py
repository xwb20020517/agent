import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.DEBUG else "INFO",
        enqueue=True,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )
