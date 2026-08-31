from __future__ import annotations


import pytest
from sqlalchemy import func, select

from app.models import AuditLog, KbSignature, Team


async def test_member_creates_team_signature(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    r = await authed_client.post("/api/kb/signatures", json={
        "signature_key": "ssh_connection_failed",
        "representative_text": "failed to connect to the host via ssh",
        "title": "SSH unreachable",
        "team_id": str(team.id),
        "status": "known-issue",
        "links": [{"label": "Runbook", "url": "https://wiki/ssh"}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["team_id"] == str(team.id)
    assert body["status"] == "known-issue"
    assert body["links"][0]["url"] == "https://wiki/ssh"
    n = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "kb_create"))
    assert n == 1


async def test_non_member_team_create_403(authed_client, db):
    other = Team(name="NotMine", slug="notmine")
    db.add(other)
    await db.flush()
    r = await authed_client.post("/api/kb/signatures", json={
        "signature_key": "k", "representative_text": "t", "title": "T",
        "team_id": str(other.id),
    })
    assert r.status_code == 403


async def test_non_admin_global_create_403(authed_client, db):
    r = await authed_client.post("/api/kb/signatures", json={
        "signature_key": "k", "representative_text": "t", "title": "T",
        "team_id": None,
    })
    assert r.status_code == 403


async def test_admin_creates_global(admin_client, db):
    r = await admin_client.post("/api/kb/signatures", json={
        "signature_key": "global_key", "representative_text": "rep", "title": "Glob",
        "team_id": None,
    })
    assert r.status_code == 201
    assert r.json()["team_id"] is None


async def test_bad_status_422(admin_client):
    r = await admin_client.post("/api/kb/signatures", json={
        "signature_key": "k", "representative_text": "t", "title": "T",
        "team_id": None, "status": "bogus",
    })
    assert r.status_code == 422


async def test_javascript_link_422(admin_client):
    r = await admin_client.post("/api/kb/signatures", json={
        "signature_key": "k", "representative_text": "t", "title": "T",
        "team_id": None, "links": [{"label": "x", "url": "javascript:alert(1)"}],
    })
    assert r.status_code == 422


async def test_duplicate_global_key_409(admin_client, db):
    payload = {"signature_key": "dup_key", "representative_text": "t", "title": "T", "team_id": None}
    a = await admin_client.post("/api/kb/signatures", json=payload)
    assert a.status_code == 201
    b = await admin_client.post("/api/kb/signatures", json=payload)
    assert b.status_code == 409


async def test_create_is_atomic_with_audit(admin_client, db, monkeypatch):
    # Audit atomicity: backfill_signature runs BEFORE write_audit + the route's single final
    # commit. Because backfill is called with commit=False, the signature insert + its
    # occurrences are NOT yet durable when write_audit runs. Force write_audit to raise
    # (simulating any failure between backfill and the final commit) and assert NEITHER the
    # signature NOR an audit row survives — they were never committed.
    #
    # NOTE: the conftest's ASGITransport runs with raise_app_exceptions=True (its default),
    # so an unhandled error in the route propagates out of the client call rather than being
    # converted to a 500 response body. We therefore assert the propagation explicitly; the
    # load-bearing assertions below (no sig, no audit after rollback) are unchanged.
    async def _boom(*a, **k):
        raise RuntimeError("audit blew up")

    monkeypatch.setattr("app.api.kb.write_audit", _boom)
    before_sigs = await db.scalar(select(func.count()).select_from(KbSignature))
    with pytest.raises(RuntimeError, match="audit blew up"):
        await admin_client.post("/api/kb/signatures", json={
            "signature_key": "atomic_key", "representative_text": "rep", "title": "Atomic",
            "team_id": None,
        })
    # Fresh read on a clean transaction: the rolled-back signature is absent...
    await db.rollback()
    after_sigs = await db.scalar(
        select(func.count()).select_from(KbSignature).where(KbSignature.signature_key == "atomic_key")
    )
    assert after_sigs == 0
    assert await db.scalar(select(func.count()).select_from(KbSignature)) == before_sigs
    # ...and no kb_create audit row for it was written either.
    audit_n = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "kb_create"))
    assert audit_n == 0
