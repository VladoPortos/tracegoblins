"""Regression (F2): the authenticated 2FA-management surface and the pre-session 2FA login-verify
surface must NOT share an IP rate-limit bucket. Before the fix both used the key `ip:{ip}` in the
single mfa_verify_limiter, so 5 failed management attempts locked out 2FA *login* for every user
behind the same NAT/IP. The fix namespaces the IP keys per surface (mfa-mgmt-ip: vs mfa-verify-ip:).
"""
from __future__ import annotations

import uuid

from app.api.mfa import _mfa_mgmt_keys
from app.security.ratelimit import mfa_verify_limiter


class _Client:
    host = "203.0.113.9"


class _Req:
    client = _Client()


class _User:
    id = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _login_verify_keys(ip: str, user_id: uuid.UUID) -> tuple[str, str]:
    # Mirror of the key tuple built inline in mfa.login_verify (kept in sync with that endpoint).
    return (f"mfa-verify-ip:{ip}", f"mfa:{user_id}")


def test_mgmt_ip_key_is_namespaced_apart_from_login_verify():
    mgmt_ip_key, _ = _mfa_mgmt_keys(_Req(), _User())
    login_ip_key, _ = _login_verify_keys("203.0.113.9", uuid.uuid4())
    assert mgmt_ip_key == "mfa-mgmt-ip:203.0.113.9"
    assert mgmt_ip_key != login_ip_key  # the shared `ip:` key was the bug


async def test_mgmt_lockout_does_not_lock_login_verify_for_other_user_same_ip():
    mfa_verify_limiter.reset_all()
    try:
        mgmt_keys = _mfa_mgmt_keys(_Req(), _User())

        # 5 failed management attempts from this IP exhaust the management budget.
        for _ in range(5):
            await mfa_verify_limiter.record_failure(*mgmt_keys)
        assert (await mfa_verify_limiter.check(*mgmt_keys)).allowed is False  # mgmt is locked

        # A DIFFERENT user attempting 2FA *login* from the SAME IP must NOT be collateral-locked.
        other_login_keys = _login_verify_keys("203.0.113.9", uuid.uuid4())
        assert (await mfa_verify_limiter.check(*other_login_keys)).allowed is True
    finally:
        mfa_verify_limiter.reset_all()


async def test_login_verify_lockout_does_not_lock_mgmt_for_other_user_same_ip():
    mfa_verify_limiter.reset_all()
    try:
        login_keys = _login_verify_keys("203.0.113.9", uuid.uuid4())
        for _ in range(5):
            await mfa_verify_limiter.record_failure(*login_keys)
        assert (await mfa_verify_limiter.check(*login_keys)).allowed is False  # login-verify locked

        # The authenticated mgmt surface for another user on the same IP stays available.
        mgmt_keys = _mfa_mgmt_keys(_Req(), _User())
        assert (await mfa_verify_limiter.check(*mgmt_keys)).allowed is True
    finally:
        mfa_verify_limiter.reset_all()
