def test_user_2fa_columns():
    from app.models import User
    c = User.__table__.c
    assert str(c["totp_secret"].type) in ("TEXT", "Text")
    assert "totp_confirmed_at" in c
    assert "totp_last_used_step" in c


def test_mfa_tables_exist():
    from app.models import MfaRecoveryCode, PendingLogin
    assert MfaRecoveryCode.__tablename__ == "mfa_recovery_codes"
    assert PendingLogin.__tablename__ == "pending_logins"
    assert "code_hash" in MfaRecoveryCode.__table__.c
    assert "expires_at" in PendingLogin.__table__.c
