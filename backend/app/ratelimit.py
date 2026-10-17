"""Rate limiting with a fixed-window counter in Redis.

Each limit is a key like `rl:chat-ip:203.0.113.7:28911234` (name : subject : window number).
INCR is atomic and the counter lives in Redis, so the limit holds across every API
instance — unlike an in-process counter, which each replica would track separately.

Fails OPEN: if Redis is unreachable, requests are allowed (and logged). For a
customer-facing assistant, availability matters more than strict limiting.
"""

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, WebSocket, status
from redis import asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limit:
    name: str  # e.g. "chat-ip"
    subject: str  # who is limited: an IP, business id, user id…
    max_requests: int
    window_seconds: int = 60


class CounterStore(Protocol):
    async def increment(self, key: str, ttl_seconds: int) -> int: ...


class RedisCounterStore:
    def __init__(self, url: str):
        self._redis = aioredis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    async def increment(self, key: str, ttl_seconds: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            # nx=True: only set the expiry when the window's key is first created.
            pipe.incr(key).expire(key, ttl_seconds, nx=True)
            count, _ = await pipe.execute()
        return int(count)


class MemoryCounterStore:
    """For tests and single-process dev without Redis."""

    def __init__(self):
        self._counts: dict[str, int] = {}

    async def increment(self, key: str, ttl_seconds: int) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]


class RateLimiter:
    def __init__(self, store: CounterStore, clock=time.time):
        self._store = store
        self._clock = clock

    async def check(self, limit: Limit) -> int | None:
        """None if allowed, otherwise the seconds until the window resets."""
        now = self._clock()
        window = int(now // limit.window_seconds)
        key = f"rl:{limit.name}:{limit.subject}:{window}"
        try:
            count = await self._store.increment(key, limit.window_seconds)
        except Exception:
            logger.warning("Rate limiter store unavailable — allowing request", exc_info=True)
            return None
        if count > limit.max_requests:
            return int(limit.window_seconds - (now % limit.window_seconds)) + 1
        return None

    async def enforce(self, *limits: Limit) -> None:
        """Raise 429 (with Retry-After) if any limit is exceeded."""
        if not get_settings().rate_limit_enabled:
            return
        for limit in limits:
            retry_after = await self.check(limit)
            if retry_after is not None:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many requests — please slow down and try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(RedisCounterStore(get_settings().redis_url))


# ---------- the limits VoxDesk applies ----------


def chat_limits(ip: str, business_id: str) -> tuple[Limit, Limit]:
    s = get_settings()
    return (
        Limit("chat-ip", ip, s.chat_limit_per_ip),
        # Per business too: protects each business's LLM budget from one noisy page.
        Limit("chat-business", business_id, s.chat_limit_per_business),
    )


def auth_limit(ip: str) -> Limit:
    return Limit("auth-ip", ip, get_settings().auth_limit_per_ip)


def upload_limit(user_id: str) -> Limit:
    return Limit("upload-user", user_id, get_settings().upload_limit_per_user)


LimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(connection: Request | WebSocket) -> str:
    # Behind a reverse proxy, uvicorn's --proxy-headers sets this from X-Forwarded-For.
    return connection.client.host if connection.client else "unknown"
