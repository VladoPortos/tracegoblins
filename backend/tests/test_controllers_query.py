from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import AwxController, ControllerTeam, Team
from app.services.controllers_query import controller_to_out


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    """Install a real Fernet key on the settings singleton so encrypt/decrypt round-trip.

    crypto._fernet() reads settings.token_enc at call time, so patching the singleton here
    covers both the test's encrypt_token(...) and the serializer's decrypt_token(...).
    """
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key


async def test_controller_to_out_masks_token_and_resolves_team_names(db):
    team = Team(name="Alpha", slug=f"alpha-{uuid.uuid4().hex[:8]}")
    db.add(team)
    await db.flush()

    c = AwxController(
        name=f"prod-{uuid.uuid4().hex[:8]}",
        base_url="https://awx.example",
        auth_token_encrypted=encrypt_token("awx_pat_supersecret3jhY"),
        verify_ssl=True,
        sync_mode="manual",
        status="connected",
        last_sync_status="ok",
        last_sync_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        last_synced_job_id=745,
    )
    db.add(c)
    await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id, awx_organization_id=2))
    await db.flush()

    out = await controller_to_out(db, c)
    assert out.id == str(c.id)
    assert out.token_masked == "awx_pat_••••3jhY"          # last4 of the plaintext
    assert "supersecret" not in out.token_masked            # plaintext never present
    # datetime on the model; Pydantic v2 serializes tz-aware datetimes as ISO-8601 with a 'Z'
    # suffix on the wire. The frontend parses via new Date()/shortTime slice — both offset-agnostic.
    assert out.last_sync_at == datetime(2026, 6, 4, tzinfo=timezone.utc)
    assert out.last_sync_at.isoformat() == "2026-06-04T00:00:00+00:00"
    assert len(out.team_assignments) == 1
    a = out.team_assignments[0]
    assert a.team_id == str(team.id) and a.team_name == "Alpha" and a.awx_organization_id == 2


async def test_controller_out_includes_sync_progress(db):
    c = AwxController(
        name=f"prog-{uuid.uuid4().hex[:8]}",
        base_url="https://awx.example.com",
        auth_token_encrypted=encrypt_token("tok"),
        verify_ssl=False,
        last_sync_status="running",
        sync_total=50,
        sync_done=12,
        sync_current_job="4821",
    )
    db.add(c)
    await db.flush()

    out = await controller_to_out(db, c)
    assert out.sync_total == 50
    assert out.sync_done == 12
    assert out.sync_current_job == "4821"
