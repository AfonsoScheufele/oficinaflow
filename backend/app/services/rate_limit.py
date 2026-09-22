from __future__ import annotations

import time
from collections import defaultdict

from redis import Redis

from app.core.config import get_settings

_local: dict[str, list[float]] = defaultdict(list)


def allow_request(key: str, *, limit: int = 30, window: int = 60) -> bool:
    settings = get_settings()
    now = time.time()
    try:
        conn = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        pipe = conn.pipeline()
        redis_key = f"rl:{key}"
        pipe.zremrangebyscore(redis_key, 0, now - window)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window)
        _, _, count, _ = pipe.execute()
        return int(count) <= limit
    except Exception:
        bucket = _local[key]
        _local[key] = [t for t in bucket if t > now - window]
        _local[key].append(now)
        return len(_local[key]) <= limit
