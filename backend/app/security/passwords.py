from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi 25.x defaults are server-appropriate (argon2id, t=3, m=64MiB, p=4).
_ph = PasswordHasher()

MIN_PASSWORD_LEN = 12
MAX_PASSWORD_LEN = 128


class PasswordPolicyError(ValueError):
    pass


def validate_password(pw: str) -> None:
    if len(pw) < MIN_PASSWORD_LEN:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(pw) > MAX_PASSWORD_LEN:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LEN} characters.")


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(stored_hash: str, pw: str) -> bool:
    """True iff pw matches. Never raises on a wrong/corrupt hash."""
    try:
        _ph.verify(stored_hash, pw)
        return True
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
