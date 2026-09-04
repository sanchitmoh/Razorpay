from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Depends(_api_key_header),
) -> str | None:
    """
    Validates the X-API-Key header against the configured secret.
    When ``settings.api_key_enabled`` is False the check is skipped so the
    demo dashboard keeps working without credentials.
    """
    if not settings.api_key_enabled:
        return None

    if not api_key or api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Invalid or missing API key. Provide a valid X-API-Key header.",
                }
            },
        )
    return api_key


# ---------------------------------------------------------------------------
# Token Bucket Rate Limiter (Upstash Redis with In-Memory fallback)
# ---------------------------------------------------------------------------

TOKEN_BUCKET_LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "last_time")
local tokens = tonumber(data[1])
local last_time = tonumber(data[2])

if not tokens then
    tokens = capacity
    last_time = now
else
    local delta = math.max(0, now - last_time)
    tokens = math.min(capacity, tokens + (delta * refill_rate))
    last_time = now
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call("HMSET", key, "tokens", tokens, "last_time", last_time)
    local ttl = math.ceil(capacity / refill_rate) + 60
    redis.call("EXPIRE", key, ttl)
    return {1, tokens}
else
    redis.call("HMSET", key, "tokens", tokens, "last_time", last_time)
    return {0, tokens}
end
"""


class TokenBucketRateLimiter:
    """
    Provider-agnostic Token Bucket rate limiter supporting:
    1. Standard Redis / any Redis provider via `REDIS_URL` (AWS ElastiCache, Redis Cloud, Docker, Azure, Dragonfly, etc.)
    2. Upstash Redis REST API via `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` (HTTP / Serverless)
    3. Thread-safe Local In-Memory Fallback
    """

    def __init__(
        self,
        capacity: int | None = None,
        refill_rate: float | None = None,
    ) -> None:
        self.capacity = capacity or settings.rate_limit_capacity
        self.refill_rate = refill_rate or settings.rate_limit_refill_rate
        # In-memory store: {client_key: {"tokens": float, "last_time": float}}
        self._memory_store: dict[str, dict[str, float]] = {}
        self._redis_client: Any = None

    def reset(self) -> None:
        """Reset in-memory state and clear client for clean testing."""
        self._memory_store.clear()
        self._redis_client = None

    def _client_key(self, request: Request) -> str:
        if request.client:
            return request.client.host
        return "127.0.0.1"

    async def _get_redis_client(self) -> Any:
        """Lazily initialize and return the async Redis connection."""
        if self._redis_client is None and settings.redis_url:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=1.5,
                    socket_connect_timeout=1.5,
                )
            except Exception as e:
                logger.warning("Failed to initialize Redis client from REDIS_URL: %s", str(e))
                self._redis_client = None
        return self._redis_client

    async def _check_standard_redis(self, key: str, requested: int = 1) -> tuple[bool, float]:
        """Query standard Redis / any Redis provider via atomic Lua script."""
        client = await self._get_redis_client()
        if client is None:
            raise RuntimeError("Redis client unavailable")

        now = time.time()
        res = await client.eval(
            TOKEN_BUCKET_LUA_SCRIPT,
            1,
            f"rate_limit:{key}",
            str(self.capacity),
            str(self.refill_rate),
            str(now),
            str(requested),
        )
        if isinstance(res, (list, tuple)):
            allowed = bool(res[0] == 1 or res[0] == "1")
            remaining = float(res[1]) if len(res) > 1 else 0.0
            return allowed, remaining
        return bool(res == 1), 0.0

    async def _check_upstash(self, key: str, requested: int = 1) -> tuple[bool, float]:
        """Query Upstash Redis REST API via Lua script.
        
        Upstash REST API expects commands as JSON arrays following Redis protocol:
        ["EVAL", script, numkeys, key1, ..., arg1, ...]
        
        Source: https://upstash.com/blog/lua-scripting-on-upstash-redis-atomic-operations-over-http
        """
        url = settings.upstash_redis_rest_url.rstrip('/')
        headers = {
            "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
            "Content-Type": "application/json",
        }
        now = time.time()
        
        # Upstash REST API format: ["EVAL", script, numkeys, key1, ..., arg1, ...]
        payload = [
            "EVAL",
            TOKEN_BUCKET_LUA_SCRIPT,
            "1",  # numkeys
            f"rate_limit:{key}",  # KEYS[1]
            str(self.capacity),    # ARGV[1]
            str(self.refill_rate), # ARGV[2]
            str(now),              # ARGV[3]
            str(requested),        # ARGV[4]
        ]
        
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", [1, self.capacity])
                allowed = bool(result[0] == 1)
                remaining = float(result[1]) if len(result) > 1 else 0.0
                return allowed, remaining
            else:
                logger.warning(
                    "Upstash Redis rate limit call failed with status %d, falling back to in-memory",
                    resp.status_code,
                )
                raise RuntimeError("Upstash error")

    def _check_memory(self, key: str, requested: int = 1) -> tuple[bool, float]:
        """Local in-memory Token Bucket check."""
        now = time.time()
        entry = self._memory_store.get(key)
        if entry is None:
            tokens = float(self.capacity)
            last_time = now
        else:
            delta = max(0.0, now - entry["last_time"])
            tokens = min(float(self.capacity), entry["tokens"] + delta * self.refill_rate)
            last_time = now

        if tokens >= requested:
            tokens -= requested
            self._memory_store[key] = {"tokens": tokens, "last_time": last_time}
            return True, tokens
        else:
            self._memory_store[key] = {"tokens": tokens, "last_time": last_time}
            return False, tokens

    async def __call__(self, request: Request) -> None:
        key = self._client_key(request)
        allowed = True
        remaining = 0.0

        if settings.redis_url:
            try:
                allowed, remaining = await self._check_standard_redis(key, requested=1)
            except Exception as e:
                logger.debug("Redis rate limit error, falling back to memory: %s", str(e))
                allowed, remaining = self._check_memory(key, requested=1)
        elif settings.upstash_redis_rest_url and settings.upstash_redis_rest_token:
            try:
                allowed, remaining = await self._check_upstash(key, requested=1)
            except Exception as e:
                logger.debug("Upstash fallback to local token bucket: %s", str(e))
                allowed, remaining = self._check_memory(key, requested=1)
        else:
            allowed, remaining = self._check_memory(key, requested=1)

        if not allowed:
            retry_after = math.ceil(max(1.0, (1.0 - remaining) / max(0.1, self.refill_rate)))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"Rate limit exceeded (Token Bucket capacity {self.capacity}, refill {self.refill_rate}/s). Retry after {retry_after}s.",
                    }
                },
                headers={"Retry-After": str(retry_after)},
            )


# Singleton Token Bucket instance
rate_limiter = TokenBucketRateLimiter()


# ---------------------------------------------------------------------------
# Request-ID Middleware
# ---------------------------------------------------------------------------


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Injects a unique ``X-Request-ID`` into every request/response cycle.
    If caller provides one, it is reused for distributed tracing.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# Request Logging Middleware
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status code, and response time for every request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        request_id = getattr(request.state, "request_id", "-")
        logger.info(
            "%s %s -> %s (%.1fms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )

        request.state.duration_ms = round(duration_ms, 2)
        return response
