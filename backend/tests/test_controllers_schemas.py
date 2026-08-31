from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.controllers_schemas import (
    ControllerCreate,
    ControllerOut,
    ControllerTeamOut,
    ControllerUpdate,
    SyncStartedOut,
    TeamAssignment,
    TestConnectionIn as ConnectionTestIn,
    TestConnectionOut as ConnectionTestOut,
)


def test_team_assignment_org_optional():
    a = TeamAssignment(team_id="t1")
    assert a.awx_organization_id is None
    b = TeamAssignment(team_id="t1", awx_organization_id=2)
    assert b.awx_organization_id == 2


def test_controller_create_defaults_and_required():
    c = ControllerCreate(name="prod", base_url="https://awx.example", token="awx_pat_xyz")
    assert c.verify_ssl is True
    assert c.sync_mode == "manual"
    assert c.sync_interval_minutes is None
    assert c.team_assignments == []
    with pytest.raises(ValidationError):
        ControllerCreate(name="prod", base_url="https://awx.example")  # token required


def test_controller_create_rejects_bad_sync_mode():
    with pytest.raises(ValidationError):
        ControllerCreate(name="p", base_url="https://x", token="t", sync_mode="hourly")


def test_controller_update_all_optional():
    u = ControllerUpdate()
    assert u.name is None and u.token is None and u.team_assignments is None


def test_controller_out_carries_masked_token_not_token():
    out = ControllerOut(
        id="i", name="prod", base_url="https://x", verify_ssl=True, sync_mode="manual",
        sync_interval_minutes=None, status="connected", last_sync_status="ok",
        last_sync_at=None, last_sync_error=None,
        token_masked="awx_pat_••••3jhY", team_assignments=[], created_at="2026-06-04T00:00:00Z",
    )
    dumped = out.model_dump()
    assert dumped["token_masked"] == "awx_pat_••••3jhY"
    assert "token" not in dumped


def test_controller_team_out_and_connection_and_sync_started():
    cto = ControllerTeamOut(team_id="t", team_name="General", awx_organization_id=None)
    assert cto.team_name == "General"
    ti = ConnectionTestIn()
    assert ti.base_url is None and ti.token is None and ti.verify_ssl is None
    to = ConnectionTestOut(ok=True, version="24.6.1", identity="cloudauto")
    assert to.ok is True and to.error is None
    ss = SyncStartedOut(status="started")
    assert ss.status == "started"
