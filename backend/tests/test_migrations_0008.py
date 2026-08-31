from __future__ import annotations

import importlib.util
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(mod_filename: str):
    path = VERSIONS / mod_filename
    spec = importlib.util.spec_from_file_location(mod_filename.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0008_is_the_head_after_0007():
    m = _load("0008_controller_sync_progress.py")
    assert m.down_revision == "0007"
    assert m.revision == "0008"


def test_0008_adds_three_progress_columns():
    src = (VERSIONS / "0008_controller_sync_progress.py").read_text()
    for col in ("sync_total", "sync_done", "sync_current_job"):
        assert col in src, f"migration must add {col}"
    assert "add_column" in src and "drop_column" in src
