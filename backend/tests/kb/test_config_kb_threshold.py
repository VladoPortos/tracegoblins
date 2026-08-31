from __future__ import annotations

from app.core.config import Settings


def test_kb_match_threshold_default():
    s = Settings(_env_file=None)
    assert s.kb_match_threshold == 0.35


def test_kb_match_threshold_env_override(monkeypatch):
    monkeypatch.setenv("KB_MATCH_THRESHOLD", "0.5")
    s = Settings(_env_file=None)
    assert s.kb_match_threshold == 0.5
