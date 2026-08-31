"""Regression tests for the SECOND QA-report hardening pass (this review).

Each test pins a finding that was verified valid and fixed. Findings judged working-as-designed
are intentionally NOT here: M2 (controller-wide sync is by design, D3), M3 (zero-team
controllers are a tested contract — see test_controllers_api.test_patch_controller_clear_assignments),
and M8 (cross-team run sharing is a product feature).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from app.core.config import settings

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    """A real Fernet key on the settings singleton so AWX token encrypt/decrypt round-trips."""
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(Fernet.generate_key().decode()))


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- H1: AWX pagination must not follow `next` off-origin (token-leak guard) ----

async def test_h1_pagination_off_origin_rejected():
    from app.awx.client import FINISHED_FILTER, AwxClient, AwxError

    base = "https://awx.example.com"
    page = {
        "count": 1,
        "next": "https://evil.example.net/api/v2/jobs/?page=2",  # different host!
        "results": [{"id": 1, "status": "successful", "url": "/api/v2/jobs/1/", "summary_fields": {}}],
    }
    with respx.mock(base_url=base) as mock:
        mock.get(f"/api/v2/jobs/?id__gt=0&order_by=id&page_size=200{FINISHED_FILTER}").mock(
            return_value=httpx.Response(200, json=page)
        )
        async with AwxClient(base, "tok", verify_ssl=False) as client:
            with pytest.raises(AwxError) as ei:
                [j async for j in client.list_jobs(0)]
    assert "off-origin" in str(ei.value)


async def test_h1_pagination_same_origin_followed():
    """A same-origin absolute `next` is still followed (no false positive)."""
    from app.awx.client import FINISHED_FILTER, AwxClient

    base = "https://awx.example.com"
    nxt = f"{base}/api/v2/jobs/?id__gt=0&order_by=id&page_size=200&page=2{FINISHED_FILTER}"
    with respx.mock(base_url=base) as mock:
        mock.get(f"/api/v2/jobs/?id__gt=0&order_by=id&page_size=200{FINISHED_FILTER}").mock(
            return_value=httpx.Response(200, json={
                "count": 2, "next": nxt,
                "results": [{"id": 1, "status": "successful", "url": "/api/v2/jobs/1/", "summary_fields": {}}],
            })
        )
        mock.get(nxt).mock(return_value=httpx.Response(200, json={
            "count": 2, "next": None,
            "results": [{"id": 2, "status": "successful", "url": "/api/v2/jobs/2/", "summary_fields": {}}],
        }))
        async with AwxClient(base, "tok", verify_ssl=False) as client:
            jobs = [j async for j in client.list_jobs(0)]
    assert [j.id for j in jobs] == [1, 2]


# --- H2: an unexpected (non-AwxError) failure must not pin status at "running" --

async def test_h2_unexpected_error_resets_running_status(db, monkeypatch):
    from app.awx.sync import sync_controller
    from app.core.crypto import encrypt_token
    from app.models import AwxController

    c = AwxController(
        name=f"boom-{uuid.uuid4().hex[:6]}", base_url="https://awx.example",
        auth_token_encrypted=encrypt_token("t"), verify_ssl=False,
    )
    db.add(c)
    await db.flush()

    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def list_jobs(self, since_id):
            raise ValueError("unexpected parser/runtime boom")
            yield  # make it an async generator

        async def list_projects(self):
            return []

    monkeypatch.setattr("app.awx.sync.AwxClient", _Boom)
    res = await sync_controller(db, c)
    assert res.status == "error"
    assert c.last_sync_status == "error"  # NOT left at "running"


# --- H3: import blobs are capped (memory / DB / payload pressure) ---------------

def test_h3_res_blob_capped():
    from app.logparser.job_events import _MAX_BLOB_CHARS, _res_blob

    out = _res_blob({"msg": "x" * (_MAX_BLOB_CHARS + 5_000)})
    assert out.endswith("…[truncated]")
    assert len(out) <= _MAX_BLOB_CHARS + len("…[truncated]")


def test_h3_runraw_join_capped():
    from app.awx.sync import MAX_RUNRAW_CHARS, _join_stdout_capped

    events = [{"stdout": "a" * 1000} for _ in range((MAX_RUNRAW_CHARS // 1000) + 50)]
    out = _join_stdout_capped(events)
    assert "truncated" in out
    assert len(out) <= MAX_RUNRAW_CHARS + 80


# --- H5: promote-global honours visibility (A1) + the password-current gate -----

async def test_h5_promote_global_404_when_admin_not_in_team(admin_client, db):
    from app.models import KbSignature, Team

    t = Team(name=f"NoAdmin-{uuid.uuid4().hex[:6]}", slug=f"na-{uuid.uuid4().hex[:6]}")
    db.add(t)
    await db.flush()
    sig = KbSignature(team_id=t.id, signature_key=f"k-{uuid.uuid4().hex[:6]}",
                      title="T", status="needs-fix", representative_text="rep")
    db.add(sig)
    await db.flush()
    # admin@example.com is in General only — NOT a member of team t -> no read path (404).
    r = await admin_client.post(f"/api/kb/signatures/{sig.id}/promote-global")
    assert r.status_code == 404


async def test_h5_promote_global_blocked_when_must_change_password(db, make_user, session_for):
    from app.models import KbSignature

    admin = await make_user(email=f"pg-{uuid.uuid4().hex[:6]}@example.com",
                            role="admin", must_change_password=True)
    sig = KbSignature(team_id=None, signature_key=f"g-{uuid.uuid4().hex[:6]}",
                      title="T", status="needs-fix", representative_text="r")
    db.add(sig)
    await db.flush()
    ac = await session_for(admin)
    r = await ac.post(f"/api/kb/signatures/{sig.id}/promote-global")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "password_change_required"


# --- H6: non-admin controller listing redacts token + foreign team assignments --

async def test_h6_non_admin_listing_redacts(client, db, make_user, session_for):
    from app.core.crypto import encrypt_token
    from app.models import AwxController, ControllerTeam, Team

    ta = Team(name=f"TA-{uuid.uuid4().hex[:6]}", slug=f"ta-{uuid.uuid4().hex[:6]}")
    tb = Team(name=f"TB-{uuid.uuid4().hex[:6]}", slug=f"tb-{uuid.uuid4().hex[:6]}")
    db.add_all([ta, tb])
    await db.flush()
    member = await make_user(email=f"mem-{uuid.uuid4().hex[:6]}@example.com", team=ta)
    c = AwxController(name=f"c-{uuid.uuid4().hex[:6]}", base_url="https://awx.example",
                      auth_token_encrypted=encrypt_token("awx_pat_supersecret99"), verify_ssl=False)
    db.add(c)
    await db.flush()
    db.add_all([
        ControllerTeam(controller_id=c.id, team_id=ta.id),
        ControllerTeam(controller_id=c.id, team_id=tb.id, awx_organization_id=7),
    ])
    await db.flush()

    mc = await session_for(member)
    r = await mc.get("/api/controllers")
    assert r.status_code == 200
    item = next(x for x in r.json() if x["id"] == str(c.id))
    assert item["token_masked"] == ""  # token metadata withheld from non-admins
    team_ids = {a["team_id"] for a in item["team_assignments"]}
    assert str(ta.id) in team_ids       # own team kept
    assert str(tb.id) not in team_ids   # other team filtered out (no enumeration)


# --- M5: /api/health returns 503 when the DB is unreachable ---------------------

async def test_m5_health_503_when_db_down(client, monkeypatch):
    import app.main as main_mod

    class _BadSession:
        async def __aenter__(self):
            raise ConnectionError("db down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(main_mod, "SessionLocal", lambda *a, **k: _BadSession())
    r = await client.get("/api/health")
    assert r.status_code == 503
    assert r.json()["db"] == "error"


# --- M6: distinct team names with the same slug base get distinct slugs (no 500) -

async def test_m6_slug_collision_resolved(admin_client):
    a = await admin_client.post("/api/admin/teams", json={"name": "Dev Team"})
    b = await admin_client.post("/api/admin/teams", json={"name": "dev team"})  # same base 'dev-team'
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["slug"] == "dev-team"
    assert b.json()["slug"] != a.json()["slug"]
    assert b.json()["slug"].startswith("dev-team")


# --- M7: 2FA disable is rate-limited; admin 2FA reset revokes target sessions ----

async def test_m7_disable_rate_limited(admin_client):
    import pyotp

    secret = (await admin_client.post("/api/auth/2fa/setup")).json()["secret"]
    assert (await admin_client.post("/api/auth/2fa/enable",
                                    json={"code": pyotp.TOTP(secret).now()})).status_code == 200
    for _ in range(5):
        assert (await admin_client.post("/api/auth/2fa/disable",
                                        json={"code": "000000"})).status_code == 400
    # 6th attempt is locked out
    assert (await admin_client.post("/api/auth/2fa/disable",
                                    json={"code": "000000"})).status_code == 429


async def test_m7_admin_reset_2fa_revokes_target_sessions(db, make_user, session_for):
    from sqlalchemy import func, select

    from app.models import Session as SessionModel

    admin = await make_user(email=f"radm-{uuid.uuid4().hex[:6]}@example.com", role="admin")
    target = await make_user(email=f"rtgt-{uuid.uuid4().hex[:6]}@example.com")
    await session_for(target)  # gives target a live session row

    async def _live() -> int:
        return await db.scalar(
            select(func.count()).select_from(SessionModel).where(
                SessionModel.user_id == target.id, SessionModel.revoked_at.is_(None))
        )

    assert await _live() >= 1
    ac = await session_for(admin)
    assert (await ac.post(f"/api/users/{target.id}/reset-2fa")).status_code == 204
    assert await _live() == 0  # target's sessions revoked for incident response


# --- M10: match_patterns serialized size is capped ------------------------------

def test_m10_match_patterns_size_capped():
    from app.api.kb_schemas import _MATCH_PATTERNS_MAX_CHARS, SignatureCreate

    big = {"k": "x" * (_MATCH_PATTERNS_MAX_CHARS + 100)}
    with pytest.raises(ValidationError):
        SignatureCreate(signature_key="k", representative_text="r", title="t", match_patterns=big)
    # a small dict is accepted
    SignatureCreate(signature_key="k", representative_text="r", title="t", match_patterns={"a": 1})


# --- M11: collab content/state integrity ---------------------------------------

async def test_m11_empty_comment_rejected(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/comments", json={"body": "   "})
    assert r.status_code == 422


async def test_m11_empty_annotation_rejected(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/annotations",
                                 json={"note": "  ", "tags": [], "links": []})
    assert r.status_code == 422


async def test_m11_edit_deleted_comment_409(authed_client):
    rid = await _upload(authed_client)
    cid = (await authed_client.post(f"/api/runs/{rid}/tasks/1/comments",
                                    json={"body": "x"})).json()["id"]
    assert (await authed_client.delete(f"/api/comments/{cid}")).status_code == 200
    r = await authed_client.patch(f"/api/comments/{cid}", json={"body": "resurrect"})
    assert r.status_code == 409


async def test_m11_reply_to_deleted_parent_422(authed_client):
    rid = await _upload(authed_client)
    parent = (await authed_client.post(f"/api/runs/{rid}/tasks/1/comments",
                                       json={"body": "p"})).json()["id"]
    assert (await authed_client.delete(f"/api/comments/{parent}")).status_code == 200
    r = await authed_client.post(f"/api/runs/{rid}/tasks/1/comments",
                                 json={"body": "child", "parent_id": parent})
    assert r.status_code == 422


# --- M12: retention ages runs by actual run time (log_time), not import time -----

async def test_m12_retention_uses_log_time(db, monkeypatch):
    from sqlalchemy import select

    from app.awx.retention import run_retention_sweep
    from app.core import config as cfg
    from app.models import Run

    monkeypatch.setattr(cfg.settings, "retention_days", 90, raising=True)
    now = datetime.now(timezone.utc)

    # Ran 200d ago but imported today -> should be DELETED (aged by log_time).
    old = Run(source="awx", owner_user_id=None, team_id=None, status="failed",
              host_count=0, task_count=0, warnings_count=0, recap=[],
              log_time=now - timedelta(days=200))
    db.add(old)
    await db.flush()
    old.created_at = now

    # Ran 1d ago but imported 300d ago -> should SURVIVE (recent by log_time).
    recent = Run(source="awx", owner_user_id=None, team_id=None, status="successful",
                 host_count=0, task_count=0, warnings_count=0, recap=[],
                 log_time=now - timedelta(days=1))
    db.add(recent)
    await db.flush()
    recent.created_at = now - timedelta(days=300)
    await db.commit()

    await run_retention_sweep(db)
    remaining = set((await db.scalars(select(Run.id))).all())
    assert old.id not in remaining     # deleted by actual age (log_time), not import age
    assert recent.id in remaining      # survives despite the old import date
