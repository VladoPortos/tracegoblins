from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import settings


@pytest.fixture(autouse=True)
def _projects_token_enc_key(monkeypatch):
    """Install a real Fernet key for all projects tests that call encrypt_token."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key
