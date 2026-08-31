from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import settings


@pytest.fixture
def _awx_token_enc_key(monkeypatch):
    """Install a real Fernet key on the settings singleton for the sync-path KB test."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key
