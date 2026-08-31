"""Two-step login tests (D2): /auth/login MFA branch + /auth/login/verify."""
from __future__ import annotations

import pyotp
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.security import totp
from app.services.mfa import issue_recovery_codes


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(Fernet.generate_key().decode()))


async def _enrolled_user(db, make_user, *, secret: str, email: str):
    u = await make_user(email=email, password="hunter2hunter2")
    u.totp_secret = encrypt_token(secret)
    u.totp_enabled = True
    await db.flush()
    return u


async def test_login_without_2fa_unchanged(client, csrf, make_user):
    """Non-2FA users still get full MeOut + session cookie on /login."""
    await make_user(email="plain-2fa@x.test", password="hunter2hunter2")
    c = await csrf()
    r = await c.post("/api/auth/login", json={"email": "plain-2fa@x.test", "password": "hunter2hunter2"})
    assert r.status_code == 200
    body = r.json()
    assert "id" in body, f"Expected MeOut with 'id', got: {body}"
    assert "mfa_required" not in body
    assert settings.session_cookie_name in {k for k in c.cookies.keys()}


async def test_login_with_2fa_requires_code_then_verifies(client, csrf, db, make_user):
    """Full 2FA login flow: pending cookie → verify → session."""
    secret = totp.generate_secret()
    await _enrolled_user(db, make_user, secret=secret, email="mfa-flow@x.test")

    c = await csrf()

    # Step 1: POST /login → mfa_required, no session cookie, pending cookie set
    r = await c.post("/api/auth/login", json={"email": "mfa-flow@x.test", "password": "hunter2hunter2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"mfa_required": True}, f"Expected mfa_required, got: {body}"
    # No real session yet
    assert settings.session_cookie_name not in r.cookies
    # Pending cookie must be set
    assert "tg_mfa_pending" in r.cookies

    # Step 2: POST /login/verify with valid TOTP → full MeOut + session cookie
    r2 = await c.post("/api/auth/login/verify", json={"code": pyotp.TOTP(secret).now()})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert "id" in body2, f"Expected MeOut with 'id', got: {body2}"
    assert settings.session_cookie_name in r2.cookies


async def test_login_verify_replay_rejected(client, csrf, db, make_user):
    """Re-using a TOTP code for a second verify session returns 401 (totp_last_used_step guard)."""
    secret = totp.generate_secret()
    await _enrolled_user(db, make_user, secret=secret, email="mfa-replay@x.test")

    c = await csrf()

    # Capture the code once (same step will be used twice)
    code = pyotp.TOTP(secret).now()

    # First login + verify with the code — must succeed
    await c.post("/api/auth/login", json={"email": "mfa-replay@x.test", "password": "hunter2hunter2"})
    r = await c.post("/api/auth/login/verify", json={"code": code})
    assert r.status_code == 200, f"First verify should succeed: {r.text}"

    # Second login attempt — get a new pending cookie
    r2 = await c.post("/api/auth/login", json={"email": "mfa-replay@x.test", "password": "hunter2hunter2"})
    assert r2.status_code == 200
    assert r2.json() == {"mfa_required": True}

    # Replay the same code → 401
    r3 = await c.post("/api/auth/login/verify", json={"code": code})
    assert r3.status_code == 401, f"Replay should be rejected (401), got {r3.status_code}: {r3.text}"


async def test_login_verify_with_recovery_code(client, csrf, db, make_user):
    """Recovery code can be used to complete 2FA login."""
    secret = totp.generate_secret()
    user = await _enrolled_user(db, make_user, secret=secret, email="mfa-recovery@x.test")
    codes = await issue_recovery_codes(db, user, n=10)
    recovery_code = codes[0]

    c = await csrf()

    # Login → pending
    r = await c.post("/api/auth/login", json={"email": "mfa-recovery@x.test", "password": "hunter2hunter2"})
    assert r.status_code == 200
    assert r.json() == {"mfa_required": True}

    # Verify with recovery code → success
    r2 = await c.post("/api/auth/login/verify", json={"code": recovery_code})
    assert r2.status_code == 200, r2.text
    assert "id" in r2.json()
    assert settings.session_cookie_name in r2.cookies


async def test_login_verify_bad_code_401(client, csrf, db, make_user):
    """Wrong TOTP code returns 401."""
    secret = totp.generate_secret()
    await _enrolled_user(db, make_user, secret=secret, email="mfa-bad@x.test")

    c = await csrf()

    r = await c.post("/api/auth/login", json={"email": "mfa-bad@x.test", "password": "hunter2hunter2"})
    assert r.status_code == 200
    assert r.json() == {"mfa_required": True}

    r2 = await c.post("/api/auth/login/verify", json={"code": "000000"})
    assert r2.status_code == 401, r2.text


async def test_login_verify_without_pending_cookie_401(client, csrf):
    """Calling /verify without a pending cookie returns 401."""
    c = await csrf()
    r = await c.post("/api/auth/login/verify", json={"code": "123456"})
    assert r.status_code == 401
