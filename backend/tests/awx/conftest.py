from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import settings


@pytest.fixture(autouse=True)
def _awx_token_enc_key(monkeypatch):
    """Install a real Fernet key on the settings singleton for AWX sync tests.

    crypto._fernet() reads settings.token_enc at call time, so the sync engine's
    decrypt_token(controller.auth_token_encrypted) and the tests' encrypt_token(...)
    both flow through this key. Matches the pattern in tests/test_crypto.py.
    """
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key
