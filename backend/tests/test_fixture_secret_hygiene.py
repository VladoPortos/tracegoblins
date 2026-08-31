from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCANNER = BACKEND_ROOT / "scripts" / "check_fixture_secrets.py"


def _scan(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), str(path)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_fixture_scanner_rejects_sensitive_json_value(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(
        json.dumps({"event_data": {"api_token": "dt0c01.real-looking-token-value"}}),
        encoding="utf-8",
    )

    result = _scan(tmp_path)

    assert result.returncode == 1
    assert "capture.json" in result.stdout
    assert "event_data.api_token" in result.stdout


def test_fixture_scanner_accepts_redacted_sensitive_value(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(
        json.dumps({"event_data": {"api_token": "[REDACTED_TEST_VALUE]"}}),
        encoding="utf-8",
    )

    result = _scan(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_checked_in_fixture_corpus_contains_no_secrets() -> None:
    result = _scan(Path(__file__).with_name("fixtures"))

    assert result.returncode == 0, result.stdout + result.stderr
