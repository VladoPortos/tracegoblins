from app.api.auth import build_me
from app.core.config import settings


async def _admin(db, make_user):
    return await make_user(email="flag-admin@x.test", role="admin")


async def test_admin_setup_required_when_flag_on(db, make_user, monkeypatch):
    monkeypatch.setattr(settings, "mfa_admin_required", True)
    admin = await _admin(db, make_user)
    me = await build_me(db, admin)
    assert me.mfa_setup_required is True


async def test_admin_not_required_when_flag_off(db, make_user, monkeypatch):
    monkeypatch.setattr(settings, "mfa_admin_required", False)
    admin = await _admin(db, make_user)
    me = await build_me(db, admin)
    assert me.mfa_setup_required is False


async def test_unenrolled_admin_is_gated_server_side(client, db, make_user, session_for, monkeypatch):
    """MFA1: with the flag on, an unenrolled admin is 403'd on data/admin routes server-side (not
    just redirected in the SPA), but can still reach /auth/me and the 2FA-setup surface to enroll."""
    monkeypatch.setattr(settings, "mfa_admin_required", True)
    admin = await make_user(email="gated-admin@x.test", role="admin")  # totp_enabled defaults False
    await session_for(admin)
    # data/admin routes are blocked with the enrollment code
    blocked = await client.get("/api/admin/users")
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "mfa_enrollment_required"
    assert (await client.get("/api/runs")).status_code == 403
    # the enrollment / auth surface stays reachable — /api/auth/* (incl. /api/auth/2fa/*) is exempt
    assert (await client.get("/api/auth/me")).status_code == 200
