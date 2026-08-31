import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import settings


@pytest.fixture
def fernet_key(monkeypatch):
    """Install a real Fernet key on the settings singleton for the duration of a test.

    crypto._fernet() reads settings.token_enc at call time, so patching the
    underlying SecretStr field flows through to encrypt/decrypt without a reload.
    """
    from pydantic import SecretStr

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key


def test_encrypt_decrypt_roundtrip(fernet_key):
    token = "awx_pat_supersecretvalue_1234"
    ciphertext = crypto.encrypt_token(token)
    assert ciphertext != token  # stored at rest is NOT the plaintext
    assert crypto.decrypt_token(ciphertext) == token


def test_ciphertext_is_non_deterministic(fernet_key):
    # Fernet embeds an IV/timestamp -> two encryptions of the same plaintext differ,
    # but both decrypt back to the original.
    token = "awx_pat_dup"
    c1 = crypto.encrypt_token(token)
    c2 = crypto.encrypt_token(token)
    assert c1 != c2
    assert crypto.decrypt_token(c1) == crypto.decrypt_token(c2) == token


def test_mask_token_shows_only_last4():
    assert crypto.mask_token("awx_pat_abcdEF12") == "awx_pat_••••EF12"
    assert crypto.mask_token("abc") == "awx_pat_••••"  # too short -> no tail
    assert crypto.mask_token("") == "awx_pat_••••"
    # CRYPTO1: a short token must NOT be echoed in full — reveal a suffix only when len > 8
    assert crypto.mask_token("ABCD") == "awx_pat_••••"        # was the whole 4-char secret
    assert crypto.mask_token("12345678") == "awx_pat_••••"    # 8-char boundary still fully masked
    assert crypto.mask_token("123456789") == "awx_pat_••••6789"


def test_missing_key_raises_token_crypto_error(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "token_enc_key", SecretStr(""))
    with pytest.raises(crypto.TokenCryptoError, match="not configured"):
        crypto.encrypt_token("anything")


def test_invalid_key_raises_token_crypto_error(monkeypatch):
    from pydantic import SecretStr

    # Non-base64 / wrong-length key -> Fernet(key) raises ValueError -> TokenCryptoError.
    monkeypatch.setattr(settings, "token_enc_key", SecretStr("not-a-valid-fernet-key"))
    with pytest.raises(crypto.TokenCryptoError, match="not a valid Fernet key"):
        crypto.encrypt_token("anything")


def test_corrupt_ciphertext_raises_token_crypto_error(fernet_key):
    with pytest.raises(crypto.TokenCryptoError, match="Cannot decrypt"):
        crypto.decrypt_token("this-is-not-valid-fernet-ciphertext")
