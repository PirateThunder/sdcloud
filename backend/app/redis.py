from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from .config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


RedisDep = Annotated[Redis, Depends(get_redis)]


async def fixed_window_limit(redis: Redis, key: str, limit: int, ttl_seconds: int) -> bool:
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.incr(key)
        pipeline.expire(key, ttl_seconds, nx=True)
        count, _ = await pipeline.execute()
    return int(count) <= limit
