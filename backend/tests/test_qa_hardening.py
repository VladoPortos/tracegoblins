"""Regression tests for the QA-report hardening pass.

Each test pins a specific finding that was verified valid and fixed.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Settings, validate_runtime_secrets

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "backend/tests/fixtures/logs"


async def _upload(client) -> str:
    text = (UPLOADS / "job_11140.txt").read_text(encoding="utf-8")
    r = await client.post("/api/runs", json={"text": text})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- #17: production secret fail-fast -----------------------------------------

def _settings(**over) -> Settings:
    base = dict(environment="production",
                secret_key=SecretStr("a-strong-random-value"),
                token_enc_key=SecretStr("MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="))
    base.update(over)
    return Settings(**base)


def test_secret_validation_passes_for_secure_production():
    validate_runtime_secrets(_settings())  # no raise


def test_secret_validation_noop_outside_production():
    # placeholder secret + empty enc key, but not production -> tolerated
    validate_runtime_secrets(_settings(environment="development",
                                       secret_key=SecretStr("change-me-in-prod"),
                                       token_enc_key=SecretStr("")))


def test_secret_validation_rejects_placeholder_secret_key():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_runtime_secrets(_settings(secret_key=SecretStr("change-me-in-prod")))


def test_secret_validation_rejects_missing_token_enc_key():
    with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY"):
        validate_runtime_secrets(_settings(token_enc_key=SecretStr("")))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("secret_key", "replace-with-64-byte-urlsafe-token", "SECRET_KEY"),
        ("token_enc_key", "replace-with-fernet-key", "TOKEN_ENC_KEY"),
        ("token_enc_key", "not-a-valid-fernet-key", "TOKEN_ENC_KEY"),
    ],
)
def test_production_rejects_documented_or_malformed_secrets(field, value, message):
    with pytest.raises(RuntimeError, match=message):
        validate_runtime_secrets(_settings(**{field: SecretStr(value)}))


# --- #2: 2FA reset honours the forced-password-change gate ---------------------

async def test_reset_2fa_blocked_when_admin_must_change_password(db, make_user, session_for):
    admin = await make_user(email="pwgate-admin@example.com", role="admin",
                            must_change_password=True)
    target = await make_user(email="pwgate-target@example.com")
    ac = await session_for(admin)
    r = await ac.post(f"/api/users/{target.id}/reset-2fa")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "password_change_required"


# --- #4: annotations / comments require a real task seq -----------------------

async def test_annotation_on_unknown_task_seq_404(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(f"/api/runs/{rid}/tasks/99999/annotations", json={"note": "x"})
    assert r.status_code == 404


async def test_comment_on_unknown_task_seq_404(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(f"/api/runs/{rid}/tasks/99999/comments", json={"body": "x"})
    assert r.status_code == 404


# --- #5: a comment may not link an annotation from a different task -----------

async def test_comment_annotation_from_other_task_is_422(authed_client):
    rid = await _upload(authed_client)
    ann = await authed_client.post(f"/api/runs/{rid}/tasks/1/annotations", json={"note": "on t1"})
    assert ann.status_code == 201
    ann_id = ann.json()["id"]
    # comment on task 2 referencing the task-1 annotation -> rejected
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/2/comments", json={"body": "x", "annotation_id": ann_id}
    )
    assert r.status_code == 422
    # same annotation on its own task (1) is still fine
    ok = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/comments", json={"body": "x", "annotation_id": ann_id}
    )
    assert ok.status_code == 201


# --- #11: mention autocomplete includes controller-team members for AWX runs ---

async def test_mentionable_includes_controller_team_members_for_awx_run(
    db, make_user, session_for
):
    from app.models import AwxController, ControllerTeam, Run, Team

    team = Team(name=f"CT-{uuid.uuid4().hex[:8]}", slug=f"ct-{uuid.uuid4().hex[:8]}")
    db.add(team)
    await db.flush()
    requester = await make_user(email="ct-req@example.com", display_name="Rita Requester", team=team)
    await make_user(email="ct-other@example.com", display_name="Otto Other", team=team)

    ctrl = AwxController(name=f"ctl-{uuid.uuid4().hex[:8]}", base_url="https://awx.example.com",
                         auth_token_encrypted="gAAAAAFake==", verify_ssl=False)
    db.add(ctrl)
    await db.flush()
    db.add(ControllerTeam(controller_id=ctrl.id, team_id=team.id, awx_organization_id=None))
    run = Run(source="awx", owner_user_id=None, team_id=None, controller_id=ctrl.id,
              awx_job_id=str(uuid.uuid4().int % 100000), awx_organization_id=2, status="failed")
    db.add(run)
    await db.flush()

    rc = await session_for(requester)
    r = await rc.get(f"/api/runs/{run.id}/mentionable")
    assert r.status_code == 200
    names = {u["display_name"] for u in r.json()}
    assert {"Rita Requester", "Otto Other"} <= names


# --- #12: state-changing run/notification endpoints honour the password gate ---

async def test_delete_run_blocked_when_must_change_password(db, make_user, session_for):
    owner = await make_user(email="del-owner@example.com")
    oc = await session_for(owner)
    rid = await _upload(oc)
    # flip the owner into the forced-password-change state, then try to delete
    owner.must_change_password = True
    await db.flush()
    r = await oc.delete(f"/api/runs/{rid}")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "password_change_required"


async def test_mark_read_blocked_when_must_change_password(db, make_user, session_for):
    user = await make_user(email="notif-gate@example.com", must_change_password=True)
    uc = await session_for(user)
    r = await uc.post("/api/notifications/read", json={"all": True})
    assert r.status_code == 403


# --- #13 / #14: link validation + length caps ---------------------------------

async def test_annotation_link_without_netloc_rejected(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/annotations",
        json={"note": "x", "links": [{"label": "bad", "url": "http:evil"}]},
    )
    assert r.status_code == 422


async def test_oversized_annotation_note_rejected(authed_client):
    rid = await _upload(authed_client)
    r = await authed_client.post(
        f"/api/runs/{rid}/tasks/1/annotations", json={"note": "a" * 20_001}
    )
    assert r.status_code == 422


# --- #18: controller name/org-id semantic validation --------------------------

def test_controller_blank_name_rejected():
    from pydantic import ValidationError
    from app.api.controllers_schemas import ControllerCreate
    with pytest.raises(ValidationError):
        ControllerCreate(name="   ", base_url="https://awx", token="t")


def test_controller_name_is_stripped():
    from app.api.controllers_schemas import ControllerCreate
    c = ControllerCreate(name="  prod  ", base_url="https://awx", token="t")
    assert c.name == "prod"


def test_controller_nonpositive_org_id_rejected():
    from pydantic import ValidationError
    from app.api.controllers_schemas import TeamAssignment
    with pytest.raises(ValidationError):
        TeamAssignment(team_id="t", awx_organization_id=0)
    with pytest.raises(ValidationError):
        TeamAssignment(team_id="t", awx_organization_id=-1)
    assert TeamAssignment(team_id="t", awx_organization_id=None).awx_organization_id is None
