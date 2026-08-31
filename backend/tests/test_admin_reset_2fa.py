import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import MfaRecoveryCode, User
from app.security import totp
from app.services.mfa import issue_recovery_codes


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(Fernet.generate_key().decode()))


async def _enrolled(db, make_user) -> User:
    u = await make_user(email="victim@x.test", password="hunter2hunter2")
    u.totp_secret = encrypt_token(totp.generate_secret())
    u.totp_enabled = True
    await db.flush()
    await issue_recovery_codes(db, u, n=10)
    return u


async def test_admin_resets_user_2fa(admin_client, db, make_user):
    u = await _enrolled(db, make_user)
    r = await admin_client.post(f"/api/users/{u.id}/reset-2fa")
    assert r.status_code == 204, r.text
    await db.refresh(u)
    assert u.totp_enabled is False
    assert u.totp_secret is None
    n = await db.scalar(select(func.count()).select_from(MfaRecoveryCode).where(MfaRecoveryCode.user_id == u.id))
    assert n == 0


async def test_non_admin_cannot_reset_2fa(authed_client, db, make_user):
    u = await _enrolled(db, make_user)
    r = await authed_client.post(f"/api/users/{u.id}/reset-2fa")
    assert r.status_code == 403


async def test_reset_unknown_user_404(admin_client):
    import uuid
    r = await admin_client.post(f"/api/users/{uuid.uuid4()}/reset-2fa")
    assert r.status_code == 404
