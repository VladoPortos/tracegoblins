from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenCryptoError(RuntimeError):
    """Raised when TOKEN_ENC_KEY is missing/invalid or a ciphertext can't be decrypted."""


def _fernet() -> Fernet:
    key = settings.token_enc
    if not key:
        raise TokenCryptoError("TOKEN_ENC_KEY is not configured")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise TokenCryptoError("TOKEN_ENC_KEY is not a valid Fernet key") from e


def encrypt_token(plaintext: str) -> str:
    """Plaintext AWX PAT -> Fernet ciphertext (str, stored in auth_token_encrypted)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Fernet ciphertext -> plaintext PAT. Raises TokenCryptoError on tamper/bad key."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise TokenCryptoError("Cannot decrypt stored AWX token") from e


def mask_token(plaintext: str) -> str:
    """Display-safe mask: 'awx_pat_••••<last4>'. Reveals the last 4 only when the token is
    comfortably longer than that — a <=8-char secret is fully masked, never echoed (CRYPTO1)."""
    last4 = plaintext[-4:] if len(plaintext) > 8 else ""
    return f"awx_pat_••••{last4}"
