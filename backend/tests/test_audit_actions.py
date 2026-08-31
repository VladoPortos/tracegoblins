"""Regression: canonical audit action strings written by the login-ish flows.

These names are load-bearing (ops dashboards / log queries key on them), so pin them.
"""
from sqlalchemy import select

from app.models import AuditLog, User


async def test_password_login_writes_login_action(client, csrf, make_user, db):
    user = await make_user(email="audit-login@example.com", password="the-real-password-1")
    c = await csrf()
    r = await c.post("/api/auth/login", json={
        "email": "audit-login@example.com", "password": "the-real-password-1",
    })
    assert r.status_code == 200
    row = await db.scalar(
        select(AuditLog).where(AuditLog.action == "login", AuditLog.actor_id == user.id)
    )
    assert row is not None


async def test_invite_accept_writes_invite_accept_action(admin_client, db):
    r = await admin_client.post(
        "/api/admin/invites", json={"email": "audit-inv@example.com", "role": "user"}
    )
    assert r.status_code == 201
    token = r.json()["link"].rsplit("/", 1)[-1]
    acc = await admin_client.post(f"/api/invites/{token}/accept", json={
        "display_name": "Audit Newbie", "password": "brand-new-pass-99",
    })
    assert acc.status_code == 201
    user = await db.scalar(select(User).where(User.email == "audit-inv@example.com"))
    row = await db.scalar(
        select(AuditLog).where(
            AuditLog.action == "invite_accept", AuditLog.actor_id == user.id
        )
    )
    assert row is not None


async def test_setup_writes_setup_complete_action(client, db):
    r = await client.post("/api/setup", json={
        "email": "audit-first@admin.test", "display_name": "First", "password": "sup3r-s3cret-pw",
    })
    assert r.status_code == 201
    admin = await db.scalar(select(User).where(User.email == "audit-first@admin.test"))
    row = await db.scalar(
        select(AuditLog).where(
            AuditLog.action == "setup_complete", AuditLog.actor_id == admin.id
        )
    )
    assert row is not None
