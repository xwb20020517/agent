from redis.asyncio import Redis

from app.core.config import settings


redis_client: Redis | None = None


async def init_redis() -> Redis:
    global redis_client
    redis_client = Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
    )
    return redis_client


def get_redis() -> Redis:
    if redis_client is None:
        raise RuntimeError("Redis client has not been initialized")
    return redis_client


async def ping_redis() -> bool:
    client = redis_client or await init_redis()
    return bool(await client.ping())


async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
