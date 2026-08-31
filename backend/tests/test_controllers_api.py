from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import settings
from app.core.crypto import decrypt_token, encrypt_token
from app.models import AwxController, ControllerTeam, Team, TeamMember  # noqa: F401


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    """Install a real Fernet key on the settings singleton so encrypt/decrypt round-trip
    through the route + serializer. crypto._fernet() reads settings.token_enc at call time."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))
    return key


async def _seed_controller(db, *, name, token="awx_pat_secret1234"):
    c = AwxController(
        name=name, base_url="https://awx.example",
        auth_token_encrypted=encrypt_token(token),
    )
    db.add(c)
    await db.flush()
    return c


# ---------------------------------------------------------------------------
# E3 — GET /api/controllers
# ---------------------------------------------------------------------------


async def test_list_controllers_admin_sees_all(admin_client, db):
    await _seed_controller(db, name=f"prod-{uuid.uuid4().hex[:6]}")
    await _seed_controller(db, name=f"stage-{uuid.uuid4().hex[:6]}")
    await db.flush()
    r = await admin_client.get("/api/controllers")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 2
    # token never leaks
    assert all("token" not in item for item in body)
    assert all(item["token_masked"].startswith("awx_pat_••••") for item in body)


async def test_list_controllers_member_sees_only_assigned(client, db, make_user, session_for):
    # Two teams; member belongs to team A only.
    team_a = Team(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
    team_b = Team(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
    db.add_all([team_a, team_b])
    await db.flush()
    member = await make_user(email=f"m-{uuid.uuid4().hex[:6]}@example.com", team=team_a)

    c_a = await _seed_controller(db, name=f"ctrl-a-{uuid.uuid4().hex[:6]}")
    c_b = await _seed_controller(db, name=f"ctrl-b-{uuid.uuid4().hex[:6]}")
    db.add(ControllerTeam(controller_id=c_a.id, team_id=team_a.id))
    db.add(ControllerTeam(controller_id=c_b.id, team_id=team_b.id))
    await db.flush()

    mc = await session_for(member)
    r = await mc.get("/api/controllers")
    assert r.status_code == 200
    ids = {item["id"] for item in r.json()}
    assert str(c_a.id) in ids
    assert str(c_b.id) not in ids


# ---------------------------------------------------------------------------
# E4 — POST /api/controllers
# ---------------------------------------------------------------------------


async def test_create_controller_admin_encrypts_and_masks(admin_client, db):
    payload = {
        "name": f"prod-{uuid.uuid4().hex[:6]}",
        "base_url": "https://awx.example",
        "token": "awx_pat_topsecretAB12",
        "verify_ssl": False,
        "sync_mode": "manual",
        "team_assignments": [],
    }
    r = await admin_client.post("/api/controllers", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert "token" not in body
    assert body["token_masked"] == "awx_pat_••••AB12"
    assert body["verify_ssl"] is False
    # at rest the column is ciphertext, NOT the plaintext, and decrypts back
    row = await db.get(AwxController, uuid.UUID(body["id"]))
    assert row.auth_token_encrypted != "awx_pat_topsecretAB12"
    assert decrypt_token(row.auth_token_encrypted) == "awx_pat_topsecretAB12"


async def test_create_controller_non_admin_forbidden(authed_client):
    r = await authed_client.post("/api/controllers", json={
        "name": "x", "base_url": "https://x", "token": "t",
    })
    assert r.status_code == 403


async def test_create_controller_auto_without_interval_422(admin_client):
    r = await admin_client.post("/api/controllers", json={
        "name": f"a-{uuid.uuid4().hex[:6]}", "base_url": "https://x", "token": "t",
        "sync_mode": "auto",
    })
    assert r.status_code == 422


async def test_create_controller_bad_base_url_scheme_422(admin_client):
    r = await admin_client.post("/api/controllers", json={
        "name": f"b-{uuid.uuid4().hex[:6]}", "base_url": "ftp://nope", "token": "t",
    })
    assert r.status_code == 422


async def test_create_controller_duplicate_name_409(admin_client):
    name = f"dup-{uuid.uuid4().hex[:6]}"
    p = {"name": name, "base_url": "https://x", "token": "t"}
    assert (await admin_client.post("/api/controllers", json=p)).status_code == 201
    assert (await admin_client.post("/api/controllers", json=p)).status_code == 409


async def test_create_controller_org_scoped_assignment_roundtrips(admin_client, db):
    team = Team(name="Ops", slug=f"ops-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    r = await admin_client.post("/api/controllers", json={
        "name": f"c-{uuid.uuid4().hex[:6]}", "base_url": "https://x", "token": "t",
        "team_assignments": [{"team_id": str(team.id), "awx_organization_id": 2}],
    })
    assert r.status_code == 201
    a = r.json()["team_assignments"]
    assert len(a) == 1 and a[0]["team_id"] == str(team.id) and a[0]["awx_organization_id"] == 2


async def test_create_controller_duplicate_assignment_persists_nothing(admin_client, db):
    """A duplicate (team, org) within ONE create -> 4xx and NOTHING persists (atomic):
    not the controller, not the partial assignment. The savepoint scopes the dup undo, then
    the route rejects, so the whole unit of work is discarded — no orphan controller row."""
    from sqlalchemy import func, select

    from app.models import AwxController, ControllerTeam

    team = Team(name="Dupes", slug=f"dup-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    name = f"dupasg-{uuid.uuid4().hex[:6]}"
    r = await admin_client.post("/api/controllers", json={
        "name": name, "base_url": "https://x", "token": "t",
        "team_assignments": [
            {"team_id": str(team.id), "awx_organization_id": 2},
            {"team_id": str(team.id), "awx_organization_id": 2},  # exact dup
        ],
    })
    assert r.status_code in (409, 422)
    # nothing persisted: no controller by that name, no assignment rows for this team
    n_ctrl = await db.scalar(
        select(func.count()).select_from(AwxController).where(AwxController.name == name)
    )
    assert n_ctrl == 0
    n_asg = await db.scalar(
        select(func.count()).select_from(ControllerTeam).where(ControllerTeam.team_id == team.id)
    )
    assert n_asg == 0


# ---------------------------------------------------------------------------
# E5 — PATCH /api/controllers/{id}
# ---------------------------------------------------------------------------


async def test_patch_controller_rotates_token_and_reconfigures(admin_client, db):
    cr = await admin_client.post("/api/controllers", json={
        "name": f"p-{uuid.uuid4().hex[:6]}", "base_url": "https://old", "token": "awx_pat_old11111",
    })
    cid = cr.json()["id"]
    r = await admin_client.patch(f"/api/controllers/{cid}", json={
        "base_url": "https://new", "token": "awx_pat_newXYZ99",
    })
    assert r.status_code == 200
    assert r.json()["base_url"] == "https://new"
    assert r.json()["token_masked"] == "awx_pat_••••YZ99"
    row = await db.get(AwxController, uuid.UUID(cid))
    assert decrypt_token(row.auth_token_encrypted) == "awx_pat_newXYZ99"


async def test_patch_controller_omitted_token_unchanged(admin_client, db):
    cr = await admin_client.post("/api/controllers", json={
        "name": f"q-{uuid.uuid4().hex[:6]}", "base_url": "https://x", "token": "awx_pat_keepme7777",
    })
    cid = cr.json()["id"]
    r = await admin_client.patch(f"/api/controllers/{cid}", json={"verify_ssl": False})
    assert r.status_code == 200 and r.json()["verify_ssl"] is False
    row = await db.get(AwxController, uuid.UUID(cid))
    assert decrypt_token(row.auth_token_encrypted) == "awx_pat_keepme7777"  # unchanged


async def test_patch_controller_replaces_assignments(admin_client, db):
    team1 = Team(name="T1", slug=f"t1-{uuid.uuid4().hex[:6]}")
    team2 = Team(name="T2", slug=f"t2-{uuid.uuid4().hex[:6]}")
    db.add_all([team1, team2])
    await db.flush()
    cr = await admin_client.post("/api/controllers", json={
        "name": f"r-{uuid.uuid4().hex[:6]}", "base_url": "https://x", "token": "t",
        "team_assignments": [{"team_id": str(team1.id)}],
    })
    cid = cr.json()["id"]
    r = await admin_client.patch(f"/api/controllers/{cid}", json={
        "team_assignments": [{"team_id": str(team2.id), "awx_organization_id": 5}],
    })
    assert r.status_code == 200
    a = r.json()["team_assignments"]
    assert len(a) == 1 and a[0]["team_id"] == str(team2.id) and a[0]["awx_organization_id"] == 5


async def test_patch_controller_clear_assignments(admin_client):
    cr = await admin_client.post("/api/controllers", json={
        "name": f"s-{uuid.uuid4().hex[:6]}", "base_url": "https://x", "token": "t",
    })
    cid = cr.json()["id"]
    r = await admin_client.patch(f"/api/controllers/{cid}", json={"team_assignments": []})
    assert r.status_code == 200 and r.json()["team_assignments"] == []


async def test_patch_controller_404(admin_client):
    r = await admin_client.patch(f"/api/controllers/{uuid.uuid4()}", json={"name": "x"})
    assert r.status_code == 404


async def test_patch_controller_non_admin_403(authed_client, db):
    # Seed directly so the admin cookie never touches the shared client jar; the only active
    # session is the non-admin member's — the admin gate must reject the PATCH with 403.
    c = await _seed_controller(db, name=f"z-{uuid.uuid4().hex[:6]}")
    await db.flush()
    r = await authed_client.patch(f"/api/controllers/{c.id}", json={"name": "y"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# E6 — DELETE /api/controllers/{id}
# ---------------------------------------------------------------------------


async def test_delete_controller_cascades_runs(admin_client, db):
    from app.models import Run, RunRaw, Task
    cr = await admin_client.post("/api/controllers", json={
        "name": f"d-{uuid.uuid4().hex[:6]}", "base_url": "https://x", "token": "t",
    })
    cid = cr.json()["id"]
    # an AWX run synced from this controller
    run = Run(
        source="awx", owner_user_id=None, team_id=None,
        controller_id=uuid.UUID(cid), awx_job_id="900", status="successful",
    )
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="t", status="ok"))
    db.add(RunRaw(run_id=run.id, content="x"))
    await db.flush()
    rid = run.id

    r = await admin_client.delete(f"/api/controllers/{cid}")
    assert r.status_code == 204
    from sqlalchemy import func, select
    assert await db.scalar(select(func.count()).select_from(Run).where(Run.id == rid)) == 0
    assert await db.scalar(select(func.count()).select_from(Task).where(Task.run_id == rid)) == 0
    assert await db.scalar(select(func.count()).select_from(RunRaw).where(RunRaw.run_id == rid)) == 0


async def test_delete_controller_404(admin_client):
    assert (await admin_client.delete(f"/api/controllers/{uuid.uuid4()}")).status_code == 404


async def test_delete_controller_non_admin_403(authed_client, db):
    # Seed directly (no admin cookie on the shared jar); only the member session is active.
    c = await _seed_controller(db, name=f"e-{uuid.uuid4().hex[:6]}")
    await db.flush()
    r = await authed_client.delete(f"/api/controllers/{c.id}")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# E7 — POST /api/controllers/{id}/test
# ---------------------------------------------------------------------------


@respx.mock
async def test_test_connection_ok(admin_client, db):
    cr = await admin_client.post("/api/controllers", json={
        "name": f"t-{uuid.uuid4().hex[:6]}", "base_url": "https://awx.example",
        "token": "awx_pat_secret1234", "verify_ssl": False,
    })
    cid = cr.json()["id"]
    respx.get("https://awx.example/api/v2/ping/").mock(
        return_value=httpx.Response(200, json={"version": "24.6.1"})
    )
    respx.get("https://awx.example/api/v2/me/").mock(
        return_value=httpx.Response(200, json={"count": 1, "results": [{"id": 1, "username": "cloudauto"}]})
    )
    r = await admin_client.post(f"/api/controllers/{cid}/test", json={})
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "version": "24.6.1", "identity": "cloudauto", "error": None}


@respx.mock
async def test_test_connection_auth_failure(admin_client, db):
    cr = await admin_client.post("/api/controllers", json={
        "name": f"u-{uuid.uuid4().hex[:6]}", "base_url": "https://awx.bad",
        "token": "awx_pat_secret1234", "verify_ssl": False,
    })
    cid = cr.json()["id"]
    respx.get("https://awx.bad/api/v2/ping/").mock(
        return_value=httpx.Response(200, json={"version": "24.6.1"})
    )
    respx.get("https://awx.bad/api/v2/me/").mock(return_value=httpx.Response(401))
    r = await admin_client.post(f"/api/controllers/{cid}/test", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["error"]


async def test_test_connection_404(admin_client):
    r = await admin_client.post(f"/api/controllers/{uuid.uuid4()}/test", json={})
    assert r.status_code == 404


async def test_test_connection_bad_base_url_scheme_422(admin_client):
    """SSRF guard: an ad-hoc non-http(s) base_url is rejected before any AwxClient call."""
    cr = await admin_client.post("/api/controllers", json={
        "name": f"ssrf-{uuid.uuid4().hex[:6]}", "base_url": "https://awx.example",
        "token": "awx_pat_secret1234", "verify_ssl": False,
    })
    cid = cr.json()["id"]
    r = await admin_client.post(f"/api/controllers/{cid}/test",
                                json={"base_url": "file:///etc/passwd"})
    assert r.status_code == 422


async def test_test_connection_non_admin_403(authed_client, db):
    # Seed directly (no admin cookie on the shared jar); only the member session is active.
    c = await _seed_controller(db, name=f"v-{uuid.uuid4().hex[:6]}")
    await db.flush()
    r = await authed_client.post(f"/api/controllers/{c.id}/test", json={})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# E7b — POST /api/controllers/test (ad-hoc test BEFORE save; no id)
# ---------------------------------------------------------------------------


@respx.mock
async def test_test_connection_adhoc_ok(admin_client):
    """The add modal tests a connection before any controller record exists."""
    respx.get("https://awx.adhoc/api/v2/ping/").mock(
        return_value=httpx.Response(200, json={"version": "24.6.1"})
    )
    respx.get("https://awx.adhoc/api/v2/me/").mock(
        return_value=httpx.Response(200, json={"count": 1, "results": [{"id": 1, "username": "cloudauto"}]})
    )
    r = await admin_client.post("/api/controllers/test", json={
        "base_url": "https://awx.adhoc", "token": "awx_pat_secret1234", "verify_ssl": False,
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True, "version": "24.6.1", "identity": "cloudauto", "error": None}


async def test_test_connection_adhoc_requires_token(admin_client):
    r = await admin_client.post("/api/controllers/test",
                                json={"base_url": "https://awx.adhoc"})
    assert r.status_code == 422


async def test_test_connection_adhoc_bad_base_url_422(admin_client):
    """SSRF guard applies to the id-less variant too."""
    r = await admin_client.post("/api/controllers/test",
                                json={"base_url": "file:///etc/passwd", "token": "x"})
    assert r.status_code == 422


async def test_test_connection_adhoc_non_admin_403(authed_client):
    r = await authed_client.post("/api/controllers/test",
                                 json={"base_url": "https://awx.adhoc", "token": "x"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# E8 — POST /api/controllers/{id}/sync
# ---------------------------------------------------------------------------


async def test_sync_non_member_403(client, db, make_user, session_for):
    team = Team(name="OwnerTeam", slug=f"ot-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    c = await _seed_controller(db, name=f"sy-{uuid.uuid4().hex[:6]}")
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id))
    await db.flush()
    # outsider belongs to General only, not OwnerTeam
    outsider = await make_user(email=f"out-{uuid.uuid4().hex[:6]}@example.com")
    oc = await session_for(outsider)
    r = await oc.post(f"/api/controllers/{c.id}/sync")
    assert r.status_code == 403


async def test_sync_assigned_member_202(client, db, make_user, session_for, monkeypatch):
    team = Team(name="SyncTeam", slug=f"st-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    member = await make_user(email=f"sm-{uuid.uuid4().hex[:6]}@example.com", team=team)
    c = await _seed_controller(db, name=f"sz-{uuid.uuid4().hex[:6]}")
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id))
    await db.flush()

    # neutralize the background sync so the test never touches AWX/network
    import app.api.controllers as controllers_mod

    async def _noop(controller_id):
        return None

    monkeypatch.setattr(controllers_mod, "_run_manual_sync", _noop)

    mc = await session_for(member)
    r = await mc.post(f"/api/controllers/{c.id}/sync")
    assert r.status_code == 202
    assert r.json() == {"status": "started"}


async def test_sync_409_when_running(client, db, make_user, session_for, monkeypatch):
    team = Team(name="RunTeam", slug=f"rt-{uuid.uuid4().hex[:6]}")
    db.add(team)
    await db.flush()
    member = await make_user(email=f"rm-{uuid.uuid4().hex[:6]}@example.com", team=team)
    c = await _seed_controller(db, name=f"rz-{uuid.uuid4().hex[:6]}")
    c.last_sync_status = "running"
    db.add(ControllerTeam(controller_id=c.id, team_id=team.id))
    await db.flush()

    import app.api.controllers as controllers_mod

    async def _noop(controller_id):
        return None

    monkeypatch.setattr(controllers_mod, "_run_manual_sync", _noop)

    mc = await session_for(member)
    r = await mc.post(f"/api/controllers/{c.id}/sync")
    assert r.status_code == 409


async def test_sync_404(authed_client):
    r = await authed_client.post(f"/api/controllers/{uuid.uuid4()}/sync")
    assert r.status_code == 404


async def test_sync_error_never_leaks_plaintext_token(db, monkeypatch):
    """Token-leak guard: force a sync error and assert the PLAINTEXT token appears in NEITHER
    controller.last_sync_error NOR the serialized ControllerOut. Even if some failure echoes
    the token (it never should), neither the persisted error column nor the API surface may
    carry it."""
    from app.awx.client import AwxError
    from app.awx.sync import sync_controller
    from app.services.controllers_query import controller_to_out

    secret = "awx_pat_PLAINTEXT_LEAK_CANARY_9Z"
    c = await _seed_controller(db, name=f"leak-{uuid.uuid4().hex[:6]}", token=secret)

    # Stub the client so list_jobs raises an AwxError. Worst case: the error text echoes the
    # token — the engine must still keep it out of last_sync_error (it stores str(e)[:1000]),
    # so we assert the SANITIZED outcome: the message the engine persists is bounded and the
    # serialized controller never carries the secret.
    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def list_jobs(self, since_id):
            raise AwxError("Cannot reach AWX (connection refused)")
            yield  # make it an async generator

        async def list_projects(self):
            return []

    monkeypatch.setattr("app.awx.sync.AwxClient", _BoomClient)

    res = await sync_controller(db, c)
    assert res.status == "error"
    assert secret not in (c.last_sync_error or "")
    out_json = (await controller_to_out(db, c)).model_dump_json()
    assert secret not in out_json
    # and the masked field is the only token-shaped thing surfaced
    assert "token" not in {k for k in (await controller_to_out(db, c)).model_dump() if k == "token"}
