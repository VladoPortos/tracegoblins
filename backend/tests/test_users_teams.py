import pytest
from sqlalchemy import func, select

from app.models import Team, User
from app.services.users_teams import (
    DefaultTeamError,
    LastTeamError,
    add_member,
    count_user_teams,
    delete_team,
    remove_member,
)


async def _user(db, email):
    u = User(email=email, password_hash="x", display_name=email.split("@")[0])
    db.add(u)
    await db.flush()
    return u


async def _team(db, name, default=False):
    t = Team(name=name, slug=name.lower(), is_default=default)
    db.add(t)
    await db.flush()
    return t


async def test_add_member_is_idempotent(db):
    u = await _user(db, "a@x.com")
    t = await _team(db, "Alpha")
    assert await add_member(db, t.id, u.id) is True
    assert await add_member(db, t.id, u.id) is False
    assert await count_user_teams(db, u.id) == 1


async def test_remove_last_team_raises(db):
    u = await _user(db, "solo@x.com")
    t = await _team(db, "Only")
    await add_member(db, t.id, u.id)
    with pytest.raises(LastTeamError):
        await remove_member(db, t.id, u.id)


async def test_remove_when_user_has_two_teams_ok(db):
    u = await _user(db, "two@x.com")
    t1 = await _team(db, "One")
    t2 = await _team(db, "Two")
    await add_member(db, t1.id, u.id)
    await add_member(db, t2.id, u.id)
    await remove_member(db, t1.id, u.id)
    assert await count_user_teams(db, u.id) == 1


async def test_remove_from_non_member_team_is_noop_not_last_team_error(db):
    # TEAM1: removing a user from a team they don't belong to is a no-op — it must NOT raise
    # LastTeamError just because that user is (separately) in exactly one other team.
    u = await _user(db, "elsewhere@x.com")
    home = await _team(db, "Home")
    other = await _team(db, "Other")
    await add_member(db, home.id, u.id)            # member of Home only (their single team)
    await remove_member(db, other.id, u.id)        # not a member of Other → no-op, no raise
    assert await count_user_teams(db, u.id) == 1   # still in Home


async def test_delete_default_team_raises(db):
    t = await _team(db, "General", default=True)
    with pytest.raises(DefaultTeamError):
        await delete_team(db, t)


async def test_delete_team_with_sole_member_raises(db):
    u = await _user(db, "orphan@x.com")
    t = await _team(db, "Lonely")
    await add_member(db, t.id, u.id)
    with pytest.raises(LastTeamError):
        await delete_team(db, t)


async def test_delete_team_ok_when_members_have_other_teams(db):
    u = await _user(db, "safe@x.com")
    keep = await _team(db, "Keep")
    drop = await _team(db, "Drop")
    await add_member(db, keep.id, u.id)
    await add_member(db, drop.id, u.id)
    await delete_team(db, drop)
    assert await db.scalar(select(func.count()).select_from(Team).where(Team.id == drop.id)) == 0
    assert await count_user_teams(db, u.id) == 1


async def test_delete_empty_team_ok(db):
    t = await _team(db, "Empty")
    await delete_team(db, t)
    assert await db.scalar(select(func.count()).select_from(Team).where(Team.id == t.id)) == 0
