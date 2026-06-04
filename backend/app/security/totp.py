from __future__ import annotations

import hashlib
import io
import secrets
import time

import pyotp
import qrcode
import qrcode.image.svg

_STEP = 30


def generate_secret() -> str:
    return pyotp.random_base32()


def otpauth_uri(secret: str, *, email: str, issuer: str = "Tracegoblins") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def qr_svg(uri: str) -> str:
    """Pure-python SVG QR (no Pillow). Returned as a string; the SPA embeds it as a data-URI img."""
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> int | None:
    """Return the matched unix timestep (int) if `code` is valid within +/-valid_window, else None.
    The step is used by the login path as a replay guard (reject a step <= last used)."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in range(-valid_window, valid_window + 1):
        t = now + offset * _STEP
        if pyotp.utils.strings_equal(str(totp.at(t)), code):
            return t // _STEP
    return None


_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no ambiguous chars


def _one_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def generate_recovery_codes(n: int = 10) -> list[str]:
    return [_one_code() for _ in range(n)]


def _normalize(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(_normalize(code).encode()).hexdigest()
