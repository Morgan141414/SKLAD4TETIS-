"""Redis Pub/Sub for real-time multi-worker sync. Falls back to no-op when Redis is unavailable."""
import asyncio
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_redis_client = None
_available = False


async def init_redis(url: str) -> bool:
    """Try to connect to Redis. Returns True if successful."""
    global _redis_client, _available
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        await _redis_client.ping()
        _available = True
        logger.info("Redis connected at %s", url)
        return True
    except ImportError:
        logger.info("redis package not installed — Pub/Sub disabled")
        return False
    except Exception as e:
        logger.info("Redis unavailable (%s) — Pub/Sub disabled", e)
        return False


async def close_redis() -> None:
    global _redis_client, _available
    if _redis_client:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
    _redis_client = None
    _available = False


async def publish(channel: str, message: str) -> None:
    """Publish a message to a Redis channel. No-op if Redis unavailable."""
    if not _available or not _redis_client:
        return
    try:
        await _redis_client.publish(channel, message)
    except Exception as e:
        logger.debug("Redis publish failed: %s", e)


async def subscribe(channel: str, callback: Callable[[str], Awaitable[None]]) -> None:
    """Subscribe to a Redis channel and call callback for each message."""
    if not _available or not _redis_client:
        return
    try:
        pubsub = _redis_client.pubsub()
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    await callback(message["data"])
                except Exception as e:
                    logger.debug("PubSub callback error: %s", e)
    except Exception as e:
        logger.debug("Redis subscribe error: %s", e)


def is_available() -> bool:
    return _available
