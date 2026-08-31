from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.runs import get_visible_run
from app.models import Run, RunShare, Team, TeamMember, User
from app.services.visibility import is_run_visible


async def _user(db, email):
    u = User(email=email, password_hash="x", display_name=email.split("@")[0])
    db.add(u)
    await db.flush()
    return u


async def _team(db, name, slug):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _run(db, owner, team_id=None):
    r = Run(source="upload", owner_user_id=owner.id, team_id=team_id, status="ok",
            host_count=0, task_count=0, warnings_count=0, recap=[])
    db.add(r)
    await db.flush()
    return r


async def test_owner_is_visible(db):
    owner = await _user(db, "vo@example.com")
    run = await _run(db, owner)
    assert await is_run_visible(db, run, owner) is True
    got = await get_visible_run(run.id, owner, db)
    assert got.id == run.id


async def test_team_owned_visible_to_member(db):
    owner = await _user(db, "to@example.com")
    member = await _user(db, "tm@example.com")
    team = await _team(db, "Sky", "sky")
    db.add(TeamMember(team_id=team.id, user_id=member.id))
    await db.flush()
    run = await _run(db, owner, team_id=team.id)
    assert await is_run_visible(db, run, member) is True
    assert (await get_visible_run(run.id, member, db)).id == run.id


async def test_team_owned_not_visible_to_non_member(db):
    owner = await _user(db, "to2@example.com")
    outsider = await _user(db, "out2@example.com")
    team = await _team(db, "Sea", "sea")
    run = await _run(db, owner, team_id=team.id)
    assert await is_run_visible(db, run, outsider) is False
    with pytest.raises(HTTPException) as ei:
        await get_visible_run(run.id, outsider, db)
    assert ei.value.status_code == 404


async def test_direct_share_visible(db):
    owner = await _user(db, "do@example.com")
    target = await _user(db, "dt@example.com")
    run = await _run(db, owner)
    db.add(RunShare(run_id=run.id, shared_with_user_id=target.id, shared_by_user_id=owner.id))
    await db.flush()
    assert await is_run_visible(db, run, target) is True
    assert (await get_visible_run(run.id, target, db)).id == run.id


async def test_team_share_visible_to_member(db):
    owner = await _user(db, "tso@example.com")
    member = await _user(db, "tsm@example.com")
    team = await _team(db, "Fog", "fog")
    db.add(TeamMember(team_id=team.id, user_id=member.id))
    await db.flush()
    run = await _run(db, owner)  # NOT team-owned; only shared to the team
    db.add(RunShare(run_id=run.id, shared_with_team_id=team.id, shared_by_user_id=owner.id))
    await db.flush()
    assert await is_run_visible(db, run, member) is True
    assert (await get_visible_run(run.id, member, db)).id == run.id


async def test_team_share_not_visible_to_non_member(db):
    owner = await _user(db, "tso2@example.com")
    outsider = await _user(db, "out3@example.com")
    team = await _team(db, "Mist", "mist")
    run = await _run(db, owner)
    db.add(RunShare(run_id=run.id, shared_with_team_id=team.id, shared_by_user_id=owner.id))
    await db.flush()
    assert await is_run_visible(db, run, outsider) is False
    with pytest.raises(HTTPException) as ei:
        await get_visible_run(run.id, outsider, db)
    assert ei.value.status_code == 404


async def test_unrelated_user_404(db):
    owner = await _user(db, "uo@example.com")
    stranger = await _user(db, "stranger@example.com")
    run = await _run(db, owner)
    assert await is_run_visible(db, run, stranger) is False
    with pytest.raises(HTTPException) as ei:
        await get_visible_run(run.id, stranger, db)
    assert ei.value.status_code == 404


async def test_missing_run_404(db):
    owner = await _user(db, "mo@example.com")
    with pytest.raises(HTTPException) as ei:
        await get_visible_run(uuid.uuid4(), owner, db)
    assert ei.value.status_code == 404


async def test_admin_has_no_auto_read_path(db):
    """A1 invariant: an admin who is not owner/member/share-target gets no visibility."""
    owner = await _user(db, "ao@example.com")
    admin = await _user(db, "aadmin@example.com")
    admin.role = "admin"
    await db.flush()
    run = await _run(db, owner)
    assert await is_run_visible(db, run, admin) is False
    with pytest.raises(HTTPException) as ei:
        await get_visible_run(run.id, admin, db)
    assert ei.value.status_code == 404
