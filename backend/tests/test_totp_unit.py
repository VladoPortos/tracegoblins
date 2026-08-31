import pyotp
from app.security import totp


def test_secret_and_uri():
    s = totp.generate_secret()
    assert len(s) >= 16
    uri = totp.otpauth_uri(s, email="a@b.test", issuer="Tracegoblins")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=Tracegoblins" in uri


def test_verify_returns_step_for_valid_and_none_for_invalid():
    s = totp.generate_secret()
    code = pyotp.TOTP(s).now()
    step = totp.verify_totp(s, code)
    assert isinstance(step, int)
    assert totp.verify_totp(s, "abc") is None  # non-numeric


def test_qr_svg_is_svg():
    svg = totp.qr_svg(totp.otpauth_uri(totp.generate_secret(), email="a@b.test", issuer="Tracegoblins"))
    assert "<svg" in svg


def test_recovery_codes_generate_and_hash():
    codes = totp.generate_recovery_codes(10)
    assert len(codes) == 10 and len(set(codes)) == 10
    h = totp.hash_recovery_code(codes[0])
    # normalization: dashes/case/space ignored
    assert h == totp.hash_recovery_code(codes[0].upper().replace("-", " - "))
    assert h != totp.hash_recovery_code(codes[1])
