import pytest

from app.security.ratelimit import SlidingWindowLimiter


@pytest.fixture
def clock(monkeypatch):
    state = {"t": 1000.0}
    monkeypatch.setattr("app.security.ratelimit.time.monotonic", lambda: state["t"])
    return state


async def test_locks_after_max_failures(clock):
    lim = SlidingWindowLimiter(max_attempts=3, window_seconds=60, lockout_seconds=120)
    assert (await lim.check("ip:1")).allowed is True
    for _ in range(3):
        await lim.record_failure("ip:1")
    decision = await lim.check("ip:1")
    assert decision.allowed is False
    assert decision.retry_after > 0


async def test_lockout_expires(clock):
    lim = SlidingWindowLimiter(max_attempts=2, window_seconds=60, lockout_seconds=100)
    for _ in range(2):
        await lim.record_failure("acct:a@b.c")
    assert (await lim.check("acct:a@b.c")).allowed is False
    clock["t"] += 101
    assert (await lim.check("acct:a@b.c")).allowed is True


async def test_reset_clears(clock):
    lim = SlidingWindowLimiter(max_attempts=2, window_seconds=60, lockout_seconds=100)
    for _ in range(2):
        await lim.record_failure("ip:9")
    await lim.reset("ip:9")
    assert (await lim.check("ip:9")).allowed is True


async def test_per_key_independent(clock):
    lim = SlidingWindowLimiter(max_attempts=2, window_seconds=60, lockout_seconds=100)
    for _ in range(2):
        await lim.record_failure("ip:1")
    assert (await lim.check("ip:1")).allowed is False
    assert (await lim.check("ip:2")).allowed is True
