"""Redis-backed cache, rate-limit store and job queue.

SRS 3.3 gives Redis 7 three jobs: "Session cache, sliding-window rate limiter,
background-job queue". SRS 2.4 lists it alongside PostgreSQL as a datastore.

Everything here degrades to an in-process equivalent when no Redis URL is
configured, so the project still runs on a laptop with nothing installed. The
difference matters and is worth stating: in-process state is per-container, so
with more than one API container a caller would get one rate-limit budget per
container rather than one budget overall. Redis is what makes the limits in
SRS 3.4 true across a fleet rather than per-process.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import settings


class Cache:
    """A small façade over Redis with an in-process fallback."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._local: dict[str, tuple[float | None, Any]] = {}
        self._connect()

    def _connect(self) -> None:
        if not settings.redis_url:
            print("[cache] no COWRIE_REDIS_URL; using the in-process fallback")
            return
        try:
            import redis

            client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30,
            )
            client.ping()
            self._client = client
            print("[cache] redis connected")
        except Exception as exc:  # noqa: BLE001
            # A cache that cannot be reached must not stop the service booting;
            # every method below still works against the local dictionary.
            print(f"[cache] redis unavailable ({exc}); using the in-process fallback")

    @property
    def backend(self) -> str:
        return "redis" if self._client is not None else "in-process"

    @property
    def healthy(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    # -- key/value ----------------------------------------------------------

    def get(self, key: str) -> str | None:
        if self._client is not None:
            try:
                return self._client.get(key)
            except Exception:
                pass
        expires, value = self._local.get(key, (None, None))
        if expires is not None and expires < time.time():
            self._local.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if self._client is not None:
            try:
                self._client.set(key, value, ex=ttl_seconds)
                return
            except Exception:
                pass
        self._local[key] = (time.time() + ttl_seconds if ttl_seconds else None, value)

    def delete(self, key: str) -> None:
        if self._client is not None:
            try:
                self._client.delete(key)
                return
            except Exception:
                pass
        self._local.pop(key, None)

    # -- sliding-window rate limiting (SRS 3.4) -----------------------------

    def hit(self, key: str, window_seconds: float) -> int:
        """Record one request and return how many fall inside the window.

        Implemented as a sorted set keyed by timestamp: drop everything older
        than the window, add this request, count what remains. That is a true
        sliding window - a fixed-window counter would let a caller send the
        whole allowance either side of a boundary and pass twice the stated
        limit.

        The four commands go in one pipeline so concurrent callers cannot
        interleave between the prune and the count.
        """
        now = time.time()
        cutoff = now - window_seconds

        if self._client is not None:
            try:
                pipe = self._client.pipeline()
                pipe.zremrangebyscore(key, 0, cutoff)
                pipe.zadd(key, {f"{now}:{time.monotonic_ns()}": now})
                pipe.zcard(key)
                pipe.expire(key, int(window_seconds) + 1)
                return int(pipe.execute()[2])
            except Exception:
                pass

        bucket = self._local.get(key, (None, []))[1] or []
        bucket = [t for t in bucket if t > cutoff]
        bucket.append(now)
        self._local[key] = (now + window_seconds, bucket)
        return len(bucket)

    def count(self, key: str, window_seconds: float) -> int:
        """How many requests fall inside the window, without recording one."""
        now = time.time()
        cutoff = now - window_seconds

        if self._client is not None:
            try:
                self._client.zremrangebyscore(key, 0, cutoff)
                return int(self._client.zcard(key))
            except Exception:
                pass

        bucket = self._local.get(key, (None, []))[1] or []
        return len([t for t in bucket if t > cutoff])


cache = Cache()
