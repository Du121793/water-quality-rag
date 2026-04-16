from __future__ import annotations

from redis.asyncio import Redis

from methods.base.logger import info, warn
from methods.config.settings import settings

redis_client: Redis | None = None


async def initialize_redis_client() -> None:
    """初始化 Redis 連線。"""

    global redis_client

    if not settings.redis_url:
        warn("Redis", "未提供 REDIS_URL，快取功能將停用")
        return

    if redis_client is None:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        info("Redis", "連線初始化完成")


async def close_redis_client() -> None:
    global redis_client

    if redis_client is not None:
        await redis_client.close()
        redis_client = None
