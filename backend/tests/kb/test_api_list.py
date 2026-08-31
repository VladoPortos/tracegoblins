from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import KbSignature, Team


async def _mk(db, *, team_id, key, title, rep, status="needs-fix", updated_at=None):
    sig = KbSignature(team_id=team_id, signature_key=key, title=title,
                      status=status, representative_text=rep)
    if updated_at is not None:
        sig.updated_at = updated_at
    db.add(sig)
    await db.flush()
    return sig


def _items(r):
    body = r.json()
    assert set(body.keys()) == {"items", "total"}
    return body["items"]


async def test_list_all_returns_global_and_my_team(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    await _mk(db, team_id=None, key="ssh_connection_failed", title="SSH glob", rep="ssh down")
    await _mk(db, team_id=team.id, key="winrm_connection_failed", title="WinRM mine", rep="winrm down")
    other = Team(name="Outsiders", slug="outsiders")
    db.add(other)
    await db.flush()
    await _mk(db, team_id=other.id, key="assertion_failed", title="Assert hidden", rep="assert")

    r = await authed_client.get("/api/kb/signatures?scope=all")
    assert r.status_code == 200
    titles = {row["title"] for row in _items(r)}
    assert "SSH glob" in titles and "WinRM mine" in titles
    assert "Assert hidden" not in titles  # other team's sig never listed


async def test_list_scope_global_only(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    await _mk(db, team_id=None, key="ssh_connection_failed", title="G", rep="g")
    await _mk(db, team_id=team.id, key="winrm_connection_failed", title="M", rep="m")
    r = await authed_client.get("/api/kb/signatures?scope=global")
    assert r.status_code == 200
    rows = _items(r)
    assert {row["title"] for row in rows} == {"G"}
    assert all(row["team_id"] is None for row in rows)


async def test_list_scope_team_only(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    await _mk(db, team_id=None, key="ssh_connection_failed", title="G2", rep="g2")
    await _mk(db, team_id=team.id, key="winrm_connection_failed", title="M2", rep="m2")
    r = await authed_client.get("/api/kb/signatures?scope=team")
    assert r.status_code == 200
    rows = _items(r)
    assert {row["title"] for row in rows} == {"M2"}
    assert all(row["team_id"] is not None for row in rows)


async def test_list_status_filter(authed_client, db):
    await _mk(db, team_id=None, key="k_open", title="Open one", rep="open", status="needs-fix")
    await _mk(db, team_id=None, key="k_done", title="Done one", rep="done", status="resolved")
    r = await authed_client.get("/api/kb/signatures?scope=global&status=resolved")
    assert r.status_code == 200
    assert {row["title"] for row in _items(r)} == {"Done one"}


async def test_list_q_matches_title_or_rep(authed_client, db):
    await _mk(db, team_id=None, key="k_match", title="Connection refused on deploy", rep="conn refused")
    await _mk(db, team_id=None, key="k_other", title="Totally unrelated thing", rep="zzz")
    r = await authed_client.get("/api/kb/signatures?scope=global&q=connection")
    assert r.status_code == 200
    titles = {row["title"] for row in _items(r)}
    assert "Connection refused on deploy" in titles
    assert "Totally unrelated thing" not in titles


async def test_list_each_row_has_occurrence_count(authed_client, db):
    await _mk(db, team_id=None, key="k_count", title="With count", rep="rep")
    r = await authed_client.get("/api/kb/signatures?scope=global")
    assert r.status_code == 200
    assert all("occurrence_count" in row for row in _items(r))


# --- pagination envelope ({items, total} + limit/offset) ---

async def test_list_envelope_shape(authed_client, db):
    await _mk(db, team_id=None, key="k_env", title="Env one", rep="rep")
    r = await authed_client.get("/api/kb/signatures?scope=global")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert isinstance(body["items"], list)
    assert body["total"] == 1
    assert len(body["items"]) == 1


async def test_list_limit_offset_and_ordering(authed_client, db):
    # Distinct updated_at values (server_default now() is constant per-txn) so the
    # updated_at DESC ordering — unchanged from the pre-pagination behavior — is deterministic.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        await _mk(db, team_id=None, key=f"k_page_{i}", title=f"P{i}", rep="rep",
                  updated_at=base + timedelta(minutes=i))

    # Newest first: P4, P3, P2, P1, P0
    r = await authed_client.get("/api/kb/signatures?scope=global&limit=2&offset=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5  # total counts ALL visible rows, not just the page
    assert [row["title"] for row in body["items"]] == ["P3", "P2"]

    r2 = await authed_client.get("/api/kb/signatures?scope=global&limit=2&offset=4")
    assert r2.status_code == 200
    assert r2.json()["total"] == 5
    assert [row["title"] for row in r2.json()["items"]] == ["P0"]


async def test_list_offset_windows_stable_when_updated_at_ties(authed_client, db):
    # All rows created in ONE transaction → identical updated_at (server_default now()
    # is constant per-txn). The id DESC tiebreaker must keep offset windows disjoint
    # and exhaustive — no row may repeat or vanish across pages.
    for i in range(7):
        await _mk(db, team_id=None, key=f"k_tie_{i}", title=f"Tie{i}", rep="rep")

    seen: list[str] = []
    for offset in range(0, 7, 3):
        r = await authed_client.get(f"/api/kb/signatures?scope=global&limit=3&offset={offset}")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 7
        seen.extend(row["id"] for row in body["items"])

    assert len(seen) == 7                 # no skips across windows
    assert len(set(seen)) == 7            # no overlaps across windows


async def test_list_default_limit_is_50(authed_client, db):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(60):
        await _mk(db, team_id=None, key=f"k_dflt_{i}", title=f"D{i}", rep="rep",
                  updated_at=base + timedelta(seconds=i))
    r = await authed_client.get("/api/kb/signatures?scope=global")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 60
    assert len(body["items"]) == 50


async def test_list_total_respects_filters_and_visibility(authed_client, db):
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    other = Team(name="Outsiders2", slug="outsiders2")
    db.add(other)
    await db.flush()
    await _mk(db, team_id=None, key="k_t1", title="T1", rep="alpha", status="resolved")
    await _mk(db, team_id=team.id, key="k_t2", title="T2", rep="alpha", status="resolved")
    await _mk(db, team_id=team.id, key="k_t3", title="T3", rep="alpha", status="needs-fix")
    await _mk(db, team_id=other.id, key="k_t4", title="T4 hidden", rep="alpha", status="resolved")

    # visibility: other team's resolved row must not count
    r = await authed_client.get("/api/kb/signatures?scope=all&status=resolved&limit=1")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2          # T1 + T2 only; T4 invisible, T3 filtered out
    assert len(body["items"]) == 1     # page capped by limit

    # q filter narrows total the same way it narrows items
    r2 = await authed_client.get("/api/kb/signatures?scope=all&q=alpha&limit=1")
    assert r2.status_code == 200
    assert r2.json()["total"] == 3     # T1, T2, T3 (T4 invisible)


async def test_list_pagination_param_validation(authed_client):
    for qs in ("limit=0", "limit=201", "limit=-1", "offset=-1"):
        r = await authed_client.get(f"/api/kb/signatures?{qs}")
        assert r.status_code == 422, qs
