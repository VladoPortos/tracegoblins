from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.logparser.stdout import parse_stdout

ROOT = Path(__file__).resolve().parents[3]  # repo root (backend/tests/logparser -> up 3)
UPLOADS = ROOT / "backend/tests/fixtures/logs"
GOLDEN = {r["file"]: r for r in json.loads(
    (ROOT / "backend/tests/fixtures/parsed_logs.json").read_text(
        encoding="utf-8"
    ))}
FILES = ["job_11140.txt", "job_11142.txt", "job_11178.txt",
         "job_11181.txt", "sample_log-1780472760441.txt"]


def _task_view(t: dict) -> dict:
    return {k: t[k] for k in ("name", "role", "full", "line", "statuses", "items", "output")}


@pytest.mark.parametrize("fname", FILES)
def test_matches_golden(fname: str) -> None:
    parsed = parse_stdout((UPLOADS / fname).read_text(encoding="utf-8"))
    g = GOLDEN[fname]
    assert len(parsed.plays) == len(g["plays"])
    assert parsed.task_count == g["taskCount"]
    assert parsed.warnings == g["warnings"]
    pm = {k: v for k, v in {"template": parsed.meta.template, "jobId": parsed.meta.job_id,
          "user": parsed.meta.user, "logTime": parsed.meta.log_time}.items() if v is not None}
    assert pm == g["meta"]
    assert [asdict(r) for r in parsed.recap] == g["recap"]
    for pp, gp in zip(parsed.plays, g["plays"]):
        assert pp.name == gp["name"]
        assert len(pp.tasks) == len(gp["tasks"])
        for pt, gt in zip(pp.tasks, gp["tasks"]):
            assert _task_view(asdict(pt)) == _task_view(gt)
