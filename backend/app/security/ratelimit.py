import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class RateDecision:
    allowed: bool
    retry_after: int


class SlidingWindowLimiter:
    """In-process sliding-window + lockout. Single-worker correct.

    With gunicorn -w N the windows are per-worker. Keep WEB_CONCURRENCY=1 for M1,
    or swap a Postgres-backed limiter behind the same async interface for multi-worker.
    """

    def __init__(self, max_attempts: int, window_seconds: int, lockout_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.lockout = lockout_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check(self, *keys: str) -> RateDecision:
        now = time.monotonic()
        async with self._lock:
            worst = 0
            for key in keys:
                until = self._locked_until.get(key, 0.0)
                if until > now:
                    worst = max(worst, int(until - now) + 1)
                    continue
                dq = self._hits[key]
                while dq and dq[0] <= now - self.window:
                    dq.popleft()
                if len(dq) >= self.max_attempts:
                    worst = max(worst, int(dq[0] + self.window - now) + 1)
            return RateDecision(allowed=worst == 0, retry_after=worst)

    async def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        async with self._lock:
            for key in keys:
                dq = self._hits[key]
                dq.append(now)
                while dq and dq[0] <= now - self.window:
                    dq.popleft()
                if len(dq) >= self.max_attempts:
                    self._locked_until[key] = now + self.lockout

    async def reset(self, *keys: str) -> None:
        async with self._lock:
            for key in keys:
                self._hits.pop(key, None)
                self._locked_until.pop(key, None)

    def reset_all(self) -> None:
        self._hits.clear()
        self._locked_until.clear()


def build_login_limiter() -> SlidingWindowLimiter:
    return SlidingWindowLimiter(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
        lockout_seconds=settings.login_lockout_seconds,
    )


login_limiter = build_login_limiter()

# Throttles the unauthenticated, CSRF-exempt first-run setup endpoint so the pre-admin
# window can't be brute-forced (race-to-create-admin) or argon2-DoS'd. Keyed on client IP.
setup_limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=300, lockout_seconds=900)

# Throttles the 6-digit TOTP / recovery-code verify surface (brute-force defence).
mfa_verify_limiter = SlidingWindowLimiter(max_attempts=5, window_seconds=300, lockout_seconds=900)
