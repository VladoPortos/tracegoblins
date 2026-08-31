from __future__ import annotations

from datetime import datetime, timezone

from app.awx.sync import SyncResult, _abs_url, _parse_iso


def test_abs_url_joins_relative_path():
    base = "https://awx.example.com"
    assert _abs_url(base, "/api/v2/jobs/745/") == "https://awx.example.com/api/v2/jobs/745/"
    # trailing slash on base is normalized (no double slash)
    assert _abs_url(base + "/", "/api/v2/jobs/745/") == "https://awx.example.com/api/v2/jobs/745/"


def test_abs_url_passthrough_when_already_absolute():
    base = "https://awx.example.com"
    abs_url = "https://other.example.com/api/v2/jobs/9/"
    assert _abs_url(base, abs_url) == abs_url
    assert _abs_url(base, None) is None


def test_parse_iso_aware_utc():
    dt = _parse_iso("2026-06-03T10:00:11.000000Z")
    assert dt == datetime(2026, 6, 3, 10, 0, 11, tzinfo=timezone.utc)
    assert dt.tzinfo is not None  # aware
    # explicit offset is honored then normalized to aware UTC value
    assert _parse_iso("2026-06-03T12:00:11+02:00") == datetime(2026, 6, 3, 10, 0, 11, tzinfo=timezone.utc)
    assert _parse_iso(None) is None
    assert _parse_iso("not-a-date") is None


def test_sync_result_shape():
    r = SyncResult(controller_id="c", status="ok", imported=3, skipped=1, last_synced_job_id=745)
    assert r.error is None and r.imported == 3 and r.last_synced_job_id == 745
