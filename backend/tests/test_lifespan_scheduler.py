from __future__ import annotations

import app.main as main_mod
from app.main import lifespan
from app.core.config import settings


async def test_lifespan_calls_start_and_stop(monkeypatch):
    calls = []

    async def _fake_start():
        calls.append("start")

    async def _fake_stop():
        calls.append("stop")

    monkeypatch.setattr(main_mod, "start_scheduler", _fake_start, raising=True)
    monkeypatch.setattr(main_mod, "stop_scheduler", _fake_stop, raising=True)
    # The default test config carries a placeholder SECRET_KEY / empty TOKEN_ENC_KEY; treat this
    # lifespan run as a non-production startup so the new fail-fast secret check is a no-op here.
    monkeypatch.setattr(settings, "environment", "development", raising=False)

    async with lifespan(main_mod.app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]
