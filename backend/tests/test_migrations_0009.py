from __future__ import annotations
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def test_0009_chains_after_0008_and_defines_tables():
    src = (VERSIONS / "0009_two_factor_auth.py").read_text()
    assert 'revision = "0009"' in src
    assert 'down_revision = "0008"' in src
    assert "mfa_recovery_codes" in src
    assert "pending_logins" in src
    assert "totp_confirmed_at" in src
    assert "totp_last_used_step" in src
    assert "alter_column" in src and "totp_secret" in src
