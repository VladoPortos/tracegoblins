import pyotp
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.models import MfaRecoveryCode, User
from app.security.ratelimit import mfa_verify_limiter


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    mfa_verify_limiter.reset_all()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(Fernet.generate_key().decode()))
    # this module exercises the MFA-required behavior; the gate is on (all its admin ops are on the
    # exempt /api/auth/2fa/* + /auth/me surface, so enrollment still works under the gate).
    monkeypatch.setattr(settings, "mfa_admin_required", True)


async def _admin(db) -> User:
    return await db.scalar(select(User).where(User.email == "admin@example.com"))


async def test_setup_enable_disable_flow(admin_client, db):
    # setup → secret + otpauth_uri + qr_svg, not yet enabled
    r = await admin_client.post("/api/auth/2fa/setup")
    assert r.status_code == 200, r.text
    body = r.json()
    secret = body["secret"]
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "<svg" in body["qr_svg"]
    assert (await _admin(db)).totp_enabled is False

    # enable with a valid code → 10 recovery codes; me.totp_enabled true
    r = await admin_client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    assert len(r.json()["recovery_codes"]) == 10
    me = (await admin_client.get("/api/auth/me")).json()
    assert me["totp_enabled"] is True
    # admin who just enabled is no longer setup-required
    assert me["mfa_setup_required"] is False

    # disable with a valid code → me.totp_enabled false
    r = await admin_client.post("/api/auth/2fa/disable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 204, r.text
    assert (await _admin(db)).totp_enabled is False


async def test_enable_rejects_bad_code(admin_client, db):
    await admin_client.post("/api/auth/2fa/setup")
    r = await admin_client.post("/api/auth/2fa/enable", json={"code": "000000"})
    assert r.status_code == 400


async def test_enable_rejects_already_enabled_without_replacing_recovery_codes(admin_client, db):
    secret = (await admin_client.post("/api/auth/2fa/setup")).json()["secret"]
    r = await admin_client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    admin = await _admin(db)
    original_hashes = (await db.execute(
        select(MfaRecoveryCode.code_hash)
        .where(MfaRecoveryCode.user_id == admin.id)
        .order_by(MfaRecoveryCode.code_hash)
    )).scalars().all()

    r = await admin_client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 400
    assert r.json()["detail"] == "2FA already enabled; disable it first"

    after_hashes = (await db.execute(
        select(MfaRecoveryCode.code_hash)
        .where(MfaRecoveryCode.user_id == admin.id)
        .order_by(MfaRecoveryCode.code_hash)
    )).scalars().all()
    assert after_hashes == original_hashes


async def test_enable_invalid_codes_are_rate_limited(admin_client):
    await admin_client.post("/api/auth/2fa/setup")
    for _ in range(5):
        r = await admin_client.post("/api/auth/2fa/enable", json={"code": "000000"})
        assert r.status_code == 400, r.text

    r = await admin_client.post("/api/auth/2fa/enable", json={"code": "000000"})
    assert r.status_code == 429
    assert r.headers["Retry-After"]


async def test_enable_enrolls_normally_after_limiter_reset(admin_client):
    mfa_verify_limiter.reset_all()
    secret = (await admin_client.post("/api/auth/2fa/setup")).json()["secret"]
    r = await admin_client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text


async def test_admin_me_setup_required_before_enrolling(admin_client):
    # Fresh admin with no TOTP → mfa_setup_required true
    me = (await admin_client.get("/api/auth/me")).json()
    assert me["role"] == "admin"
    assert me["mfa_setup_required"] is True


async def test_setup_rejected_when_already_enabled(admin_client):
    # Enroll first.
    secret = (await admin_client.post("/api/auth/2fa/setup")).json()["secret"]
    r = await admin_client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    # SECURITY: re-running /setup while enabled must be refused (would otherwise flip
    # totp_enabled→False and roll the secret without a code — an MFA-disable bypass).
    r = await admin_client.post("/api/auth/2fa/setup")
    assert r.status_code == 400, r.text
