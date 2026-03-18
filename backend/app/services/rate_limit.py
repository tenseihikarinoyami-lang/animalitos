from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, Request, status

from app.core.config import settings


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self._attempts = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        bucket = self._attempts[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please wait a moment and try again.",
            )
        bucket.append(now)


rate_limiter = InMemoryRateLimiter()


def _build_key(prefix: str, request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{prefix}:{request.url.path}:{client_host}"


async def limit_auth_requests(request: Request) -> None:
    rate_limiter.check(
        key=_build_key("auth", request),
        limit=settings.rate_limit_auth_attempts,
        window_seconds=settings.rate_limit_window_seconds,
    )


async def limit_admin_requests(request: Request) -> None:
    rate_limiter.check(
        key=_build_key("admin", request),
        limit=settings.rate_limit_admin_attempts,
        window_seconds=settings.rate_limit_window_seconds,
    )
