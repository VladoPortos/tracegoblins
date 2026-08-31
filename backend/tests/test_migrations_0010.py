from __future__ import annotations
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def test_0010_chains_after_0009_and_adds_launched_at():
    src = (VERSIONS / "0010_run_launched_at.py").read_text()
    assert 'revision = "0010"' in src
    assert 'down_revision = "0009"' in src
    assert "launched_at" in src
    assert "add_column" in src
    assert "drop_column" in src
