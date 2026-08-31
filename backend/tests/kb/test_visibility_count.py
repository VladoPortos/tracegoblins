from __future__ import annotations

import pytest

from app.kb.service import visible_occurrence_count
from app.models import (
    KbOccurrence, KbSignature, Run, Task, Team, TeamMember, User,
)
from app.security.passwords import hash_password
from tests.kb._blobs import SSH_BLOB_A

pytestmark = pytest.mark.asyncio


async def _team(db, name, slug):
    t = Team(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _user(db, team, email):
    u = User(email=email, password_hash=hash_password("hunter2hunter2"),
             display_name=email.split("@")[0], is_active=True)
    db.add(u)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=u.id))
    await db.flush()
    return u


async def _occ(db, *, sig, owner, team_id, host="h"):
    run = Run(source="upload", owner_user_id=owner.id, team_id=team_id,
              status="unreachable", template_name="tpl")
    db.add(run)
    await db.flush()
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="Connect",
                status="unreachable", hosts={host: "unreachable"}, error=SSH_BLOB_A))
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1, host=host))
    await db.flush()
    return run


async def test_invisible_run_is_not_counted(db):
    viewer_team = await _team(db, "Viewer", "viewer")
    viewer = await _user(db, viewer_team, "viewer@example.com")
    other_team = await _team(db, "Other", "other")
    other = await _user(db, other_team, "other@example.com")

    sig = KbSignature(team_id=None, signature_key="ssh_connection_failed", title="g",
                      category="connectivity", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()

    # Run 1: owned by the viewer (visible). Run 2: owned by 'other', team-owned by Other,
    # never shared with the viewer (invisible to the viewer).
    await _occ(db, sig=sig, owner=viewer, team_id=viewer_team.id)
    await _occ(db, sig=sig, owner=other, team_id=other_team.id)

    n = await visible_occurrence_count(db, sig.id, viewer)
    assert n == 1  # only the viewer's own run counts; the invisible run is excluded (A1)


async def test_viewer_own_personal_upload_is_counted(db):
    # The owner path: a PERSONAL upload (team_id=None) owned by the viewer must count toward
    # "seen in N runs". This is the path _run_visible_cond INCLUDES but runs.py::_team_scope_base
    # deliberately EXCLUDES — proving we mirror is_run_visible (owner path), not _team_scope_base.
    viewer_team = await _team(db, "OwnP", "ownp")
    viewer = await _user(db, viewer_team, "ownp@example.com")
    sig = KbSignature(team_id=None, signature_key="ssh_connection_failed", title="g",
                      category="connectivity", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()

    # team_id=None -> a personal upload; only the owner path can make it visible.
    await _occ(db, sig=sig, owner=viewer, team_id=None)
    n = await visible_occurrence_count(db, sig.id, viewer)
    assert n == 1  # the viewer's own personal upload IS counted (owner path)


async def test_distinct_runs_not_tasks(db):
    team = await _team(db, "Dist", "dist")
    u = await _user(db, team, "dist@example.com")
    sig = KbSignature(team_id=team.id, signature_key="ssh_connection_failed", title="t",
                      category="connectivity", status="known-issue",
                      representative_text="failed to connect to the host via ssh")
    db.add(sig)
    await db.flush()

    run = Run(source="upload", owner_user_id=u.id, team_id=team.id, status="unreachable")
    db.add(run)
    await db.flush()
    # two occurrences on the SAME run (two tasks) -> counts as ONE run.
    db.add(Task(run_id=run.id, seq=1, play_name="p", name="A", status="unreachable",
                hosts={"a": "unreachable"}, error=SSH_BLOB_A))
    db.add(Task(run_id=run.id, seq=2, play_name="p", name="B", status="unreachable",
                hosts={"b": "unreachable"}, error=SSH_BLOB_A))
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=1, host="a"))
    db.add(KbOccurrence(signature_id=sig.id, run_id=run.id, task_seq=2, host="b"))
    await db.flush()

    assert await visible_occurrence_count(db, sig.id, u) == 1
