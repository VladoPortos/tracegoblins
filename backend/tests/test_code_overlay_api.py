import asyncio
import os
import shutil
import uuid

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models import AwxController, ControllerTeam, Project, Run, RunNode, RunNodeResult, Team, TeamMember, User
from app.projects import git
from app.projects.storage import project_repo_path
from app.security.passwords import hash_password

pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(shutil.which("git") is None, reason="git binary not on PATH")]


@pytest.fixture(autouse=True)
def _token_enc_key(monkeypatch):
    """Install a real Fernet key so encrypt_token works in all tests in this module."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "token_enc_key", SecretStr(key))


TASKS_YML = (
    "---\n"
    "- name: install nginx\n"
    "  ansible.builtin.apt:\n"
    '    name: "{{ pkg }}"\n'
    "- name: windows only\n"
    "  ansible.windows.win_package: {}\n"
    '  when: ansible_os_family == "Windows"\n'
)

# A multi-task file where a/c/e (lines 2/7/12) execute and b/d (lines 4/9) never do — used to
# prove never-run ghosts anchor to their nearest PRECEDING executed sibling, not all to node a.
PLAY_YML = (
    "---\n"                            # 1
    "- name: a ran\n"                  # 2
    "  ansible.builtin.debug: {}\n"    # 3
    "- name: b never\n"                # 4
    "  ansible.builtin.debug: {}\n"    # 5
    "  when: false\n"                  # 6
    "- name: c ran\n"                  # 7
    "  ansible.builtin.debug: {}\n"    # 8
    "- name: d never\n"                # 9
    "  ansible.builtin.debug: {}\n"    # 10
    "  when: false\n"                  # 11
    "- name: e ran\n"                  # 12
    "  ansible.builtin.debug: {}\n"    # 13
)

# outer (2) and tail (11) run; the `cond block` (4) and its two children (7, 9) never run —
# proves a wholly-never-run block becomes a ghost PARENT with its children nested under it.
BLOCK_YML = (
    "---\n"                            # 1
    "- name: outer ran\n"              # 2
    "  ansible.builtin.debug: {}\n"    # 3
    "- name: cond block\n"             # 4
    "  when: do_it\n"                  # 5
    "  block:\n"                       # 6
    "    - name: inner one\n"          # 7
    "      ansible.builtin.debug: {}\n"  # 8
    "    - name: inner two\n"          # 9
    "      ansible.builtin.debug: {}\n"  # 10
    "- name: tail ran\n"               # 11
    "  ansible.builtin.debug: {}\n"    # 12
)

# early (2) never runs, late (5) does — proves a ghost BEFORE the first executed task leads INTO
# it rather than branching off a later task.
PREFIX_YML = (
    "---\n"                            # 1
    "- name: early never\n"            # 2
    "  ansible.builtin.debug: {}\n"    # 3
    "  when: false\n"                  # 4
    "- name: late ran\n"               # 5
    "  ansible.builtin.debug: {}\n"    # 6
)

# 'including.yml' runs 'ran here' (line 2) then a conditional include of 'included.yml' (line 4) that
# was SKIPPED — so included.yml's tasks never ran and must surface as ghosts off the include (NR2).
INCLUDING_YML = (
    "---\n"                                       # 1
    "- name: ran here\n"                          # 2
    "  ansible.builtin.debug: {}\n"               # 3
    "- name: maybe include\n"                     # 4
    "  ansible.builtin.include_tasks: included.yml\n"  # 5
    "  when: do_it\n"                             # 6
)
INCLUDED_YML = (
    "- name: deep one\n"                          # 1
    "  ansible.builtin.debug: {}\n"               # 2
    "- name: deep two\n"                          # 3
    "  ansible.builtin.debug: {}\n"               # 4
)

# a 2-play playbook file: play 'web' (line 1) runs 'deploy' (line 3); play 'db' (line 5) is never
# entered, so its 'migrate' (line 7) must NOT anchor to 'deploy' across the play boundary (NR4).
MULTIPLAY_YML = (
    "- hosts: web\n"                   # 1
    "  tasks:\n"                       # 2
    "    - name: deploy\n"             # 3
    "      ansible.builtin.debug: {}\n"  # 4
    "- hosts: db\n"                    # 5
    "  tasks:\n"                       # 6
    "    - name: migrate\n"            # 7
    "      ansible.builtin.debug: {}\n"  # 8
)

# inline task (2) runs; the `import_tasks` line (5) is a STATIC import — it emits no runner event for
# the directive line (its content is pre-expanded), so it must NOT be flagged never-run/ghost (OV3).
IMPORT_YML = (
    "---\n"                                    # 1
    "- name: inline ran\n"                     # 2
    "  ansible.builtin.debug: {}\n"            # 3
    "- name: pull in more\n"                   # 4
    "  ansible.builtin.import_tasks: more.yml\n"  # 5
)

# `ran first` (2) runs; the whole `cond block` (4) — with block/rescue/always parts — never runs,
# proving rescue/always render as SEPARATE sub-branches off the ghost block.
RESCUE_YML = (
    "---\n"                            # 1
    "- name: ran first\n"              # 2
    "  ansible.builtin.debug: {}\n"    # 3
    "- name: cond block\n"             # 4
    "  when: gate\n"                   # 5
    "  block:\n"                       # 6
    "    - name: body task\n"          # 7
    "      ansible.builtin.debug: {}\n"  # 8
    "  rescue:\n"                      # 9
    "    - name: rescue task\n"        # 10
    "      ansible.builtin.debug: {}\n"  # 11
    "  always:\n"                      # 12
    "    - name: always task\n"        # 13
    "      ansible.builtin.debug: {}\n"  # 14
)


async def _get_or_create_general(db):
    t = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    if t is None:
        t = Team(name="General", slug="general", is_default=True)
        db.add(t)
        await db.flush()
    return t


async def _get_or_create_member(db, gen):
    u = await db.scalar(select(User).where(User.email == "member@example.com"))
    if u is not None:
        return u
    u = User(email="member@example.com", role="user",
             password_hash=hash_password("hunter2hunter2"),
             display_name="member", is_active=True)
    db.add(u)
    await db.flush()
    db.add(TeamMember(team_id=gen.id, user_id=u.id))
    await db.flush()
    return u


async def _origin(tmp_path):
    src = tmp_path / "origin"
    src.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    async def run(*args):
        p = await asyncio.create_subprocess_exec(*args, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        assert p.returncode == 0, err.decode()
        return out.decode()

    await run("git", "init", "-q", "-b", "main", str(src))
    (src / "roles").mkdir()
    (src / "roles" / "app.yml").write_text(TASKS_YML)
    (src / "play.yml").write_text(PLAY_YML)
    (src / "block.yml").write_text(BLOCK_YML)
    (src / "prefix.yml").write_text(PREFIX_YML)
    (src / "rescue.yml").write_text(RESCUE_YML)
    (src / "import.yml").write_text(IMPORT_YML)
    (src / "multiplay.yml").write_text(MULTIPLAY_YML)
    (src / "including.yml").write_text(INCLUDING_YML)
    (src / "included.yml").write_text(INCLUDED_YML)
    await run("git", "-C", str(src), "add", "-A")
    await run("git", "-C", str(src), "commit", "-qm", "c1")
    sha = (await run("git", "-C", str(src), "rev-parse", "HEAD")).strip()
    return src, sha


async def _seed(db, tmp_path, monkeypatch, *, sha, cloned=True):
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    gen = await _get_or_create_general(db)
    member = await _get_or_create_member(db, gen)
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git",
                status="cloned" if cloned else "pending", organization_id=2)
    db.add(p); await db.flush()
    run = Run(source="awx", status="changed", owner_user_id=member.id, controller_id=c.id,
              project_id=19, scm_revision=sha)
    db.add(run); await db.flush()
    db.add(RunNode(run_id=run.id, node_id="root", parent_node_id=None, counter=0, depth=-1,
                   node_type="playbook", name="pb", status="ok", child_count=1))
    db.add(RunNode(run_id=run.id, node_id="play-1", parent_node_id="root", counter=1, depth=0,
                   node_type="play", name="play", status="ok", child_count=1))
    db.add(RunNode(run_id=run.id, node_id="t1", parent_node_id="play-1", counter=2, depth=1,
                   node_type="task", name="install nginx", status="ok",
                   action="ansible.builtin.apt", task_path="roles/app.yml:2",
                   args={"name": "nginx"}))
    db.add(RunNodeResult(run_id=run.id, node_id="t1", host="h1", status="ok",
                         result={"invocation": {"module_args": {"name": "nginx", "state": "present"}}}))
    await db.commit()
    if cloned:
        src = tmp_path / "origin"
        await git.clone_or_fetch(str(src), project_repo_path(p.id), auth_type="none",
                                 username=None, secret=None, max_bytes=10**9, timeout=60)
    return run


async def test_source_returns_yaml_and_focus_line(authed_client, db, tmp_path, monkeypatch):
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    r = await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "roles/app.yml" and body["focus_line"] == 2
    assert body["ref"] == sha and "install nginx" in body["content"]
    assert body["executed_lines"] == [2] and body["unavailable"] is None


async def test_source_for_never_run_ghost_node(authed_client, db, tmp_path, monkeypatch):
    """Clicking 'View source' on a never-run ghost (id `nr:file:line`) must return its YAML, not 404
    (OV5/FE1). roles/app.yml line 5 (windows only) is never-run; the ghost id is nr:roles/app.yml:5."""
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    r = await authed_client.get(f"/api/runs/{run.id}/ghost-source",
                                params={"file": "roles/app.yml", "line": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["unavailable"] is None
    assert body["path"] == "roles/app.yml" and body["focus_line"] == 5
    assert "windows only" in body["content"]
    assert 5 in body["never_run_lines"] and body["resolved"] == []


async def test_source_flags_revision_mismatch(authed_client, db, tmp_path, monkeypatch):
    """A recorded line past EOF (the clone doesn't match the run's revision) is flagged, not silently
    dropped (OV8). roles/app.yml has 7 lines; a node recorded at line 999 must set revision_mismatch."""
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    db.add(RunNode(run_id=run.id, node_id="off", parent_node_id="play-1", counter=9, depth=1,
                   node_type="task", name="phantom", status="ok", task_path="roles/app.yml:999"))
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/nodes/off/source")).json()
    assert body["revision_mismatch"] is True


async def test_source_in_range_is_not_flagged_mismatch(authed_client, db, tmp_path, monkeypatch):
    # a clean run (all recorded lines within the file) must NOT be flagged (OV8)
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    ok = (await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")).json()
    assert ok["revision_mismatch"] is False


async def test_source_unknown_node_404(authed_client, db, tmp_path, monkeypatch):
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    r = await authed_client.get(f"/api/runs/{run.id}/nodes/nope/source")
    assert r.status_code == 404


async def test_source_not_cloned_degrades(authed_client, db, tmp_path, monkeypatch):
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha, cloned=False)
    r = await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")
    assert r.status_code == 200 and r.json()["unavailable"] == "not_cloned"
    assert r.json()["content"] is None


async def test_source_visibility_404_for_outsider(client, db, tmp_path, monkeypatch, make_user, session_for):
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    other = Team(name="other", slug="other")
    db.add(other); await db.flush()
    outsider = await make_user(email="outsider@example.com", role="user", team=other)
    await session_for(outsider)
    r = await client.get(f"/api/runs/{run.id}/nodes/t1/source")
    assert r.status_code == 404


async def test_source_pairs_resolved_value_with_source_expr(authed_client, db, tmp_path, monkeypatch):
    """VV-C: the rendered value (module_args 'name'='nginx') is paired with its source expr from the
    YAML (roles/app.yml line 4: name: \"{{ pkg }}\")."""
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    body = (await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")).json()
    name = next(r for r in body["resolved"] if r["key"] == "name")
    assert name["value"] == "nginx" and name["expr"] == "{{ pkg }}"


async def test_source_resolves_recorded_values(authed_client, db, tmp_path, monkeypatch):
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    body = (await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")).json()
    resolved = {r["key"]: r for r in body["resolved"]}
    # module_args (the rendered per-host args) are the gold source
    assert resolved["name"]["value"] == "nginx" and resolved["name"]["source"] == "module_args"
    assert resolved["state"]["value"] == "present"
    assert resolved["name"]["host"] == "h1"
    assert body["hosts"] == ["h1"]


async def test_resolved_marks_unrendered_template_not_recorded(db):
    # pure helper: an arg whose value still holds a raw {{ }} → recorded=False
    from app.services.code_overlay import resolved_values
    from app.models import RunNode
    node = RunNode(run_id=uuid.uuid4(), node_id="n", node_type="task", name="t",
                   args={"name": "{{ inner.deep }}"}, when_expr=None)
    out = {r.key: r for r in resolved_values(node, [])}
    assert out["name"].recorded is False and out["name"].value is None
    assert out["name"].expr == "{{ inner.deep }}" and out["name"].source == "task_args"
    assert out["name"].host is None


async def test_resolved_no_log_censored_passthrough(db):
    # AWX no_log results arrive with module_args already censored; resolved_values must
    # surface them verbatim (recorded=True, source="module_args") and never re-derive.
    from app.services.code_overlay import resolved_values
    from app.models import RunNode, RunNodeResult
    CENSORED = "the output has been hidden due to the fact that 'no_log: true' was specified for this result"
    node = RunNode(run_id=uuid.uuid4(), node_id="n", node_type="task", name="t",
                   args={"password": "{{ vault_pass }}"}, when_expr=None)
    result = RunNodeResult(
        run_id=node.run_id, node_id="n", host="h1", status="ok",
        result={"invocation": {"module_args": {"password": CENSORED}}},
    )
    out = {r.key: r for r in resolved_values(node, [result])}
    assert "password" in out
    assert out["password"].recorded is True
    assert out["password"].source == "module_args"
    assert out["password"].value == CENSORED


async def test_when_by_line_reads_static_when_text(db, tmp_path, monkeypatch):
    # roles/app.yml line 5 = "windows only", which carries a `when:` on line 7 (PT2 condition text)
    from app.services.code_overlay import when_by_line
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    whens = await when_by_line(db, run, {"roles/app.yml"})
    assert whens.get(("roles/app.yml", 5)) == 'ansible_os_family == "Windows"'


async def test_resolved_values_tolerates_malformed_invocation(db):
    # PATH3: a non-dict res.invocation must not raise AttributeError (500) — degrade gracefully
    from app.services.code_overlay import resolved_values
    from app.models import RunNode, RunNodeResult
    node = RunNode(run_id=uuid.uuid4(), node_id="n", node_type="task", name="t",
                   action="ansible.builtin.command")
    bad = RunNodeResult(run_id=node.run_id, node_id="n", host="h1", status="ok",
                        result={"invocation": "not-a-dict", "msg": "x"})
    out = resolved_values(node, [bad])   # must not raise
    assert all(r.source != "module_args" for r in out)


async def test_resolved_set_fact_surfaces_ansible_facts(db):
    # set_fact stores its results in res.ansible_facts — resolved_values must surface them (VV-SETFACT)
    from app.services.code_overlay import resolved_values
    from app.models import RunNode, RunNodeResult
    node = RunNode(run_id=uuid.uuid4(), node_id="n", node_type="task", name="set vars",
                   action="ansible.builtin.set_fact")
    res = RunNodeResult(run_id=node.run_id, node_id="n", host="h1", status="ok",
                        result={"ansible_facts": {"app_port": 8080, "app_name": "web"}})
    out = {r.key: r for r in resolved_values(node, [res])}
    assert out["app_port"].value == 8080 and out["app_port"].source == "set_fact"
    assert out["app_port"].recorded is True and out["app_port"].host == "h1"
    assert out["app_name"].value == "web"


async def test_resolved_debug_surfaces_msg(db):
    # debug prints res.msg — surface it (VV-SETFACT)
    from app.services.code_overlay import resolved_values
    from app.models import RunNode, RunNodeResult
    node = RunNode(run_id=uuid.uuid4(), node_id="n", node_type="task", name="show",
                   action="ansible.builtin.debug")
    res = RunNodeResult(run_id=node.run_id, node_id="n", host="h1", status="ok",
                        result={"msg": "deploy finished"})
    out = {r.key: r for r in resolved_values(node, [res])}
    assert out["msg"].value == "deploy finished" and out["msg"].source == "debug"


async def test_resolved_rep_host_requires_module_args(db):
    # an earlier dict result WITHOUT module_args must not be picked as the representative (VV-D)
    from app.services.code_overlay import resolved_values
    from app.models import RunNode, RunNodeResult
    node = RunNode(run_id=uuid.uuid4(), node_id="n", node_type="task", name="t",
                   action="ansible.builtin.command")
    no_args = RunNodeResult(run_id=node.run_id, node_id="n", host="h1", status="ok",
                            result={"rc": 0})  # dict, but no invocation.module_args
    with_args = RunNodeResult(run_id=node.run_id, node_id="n", host="h2", status="ok",
                              result={"invocation": {"module_args": {"cmd": "ls"}}})
    out = {r.key: r for r in resolved_values(node, [no_args, with_args])}
    assert out["cmd"].value == "ls" and out["cmd"].source == "module_args" and out["cmd"].host == "h2"


async def test_source_marks_never_run_lines(authed_client, db, tmp_path, monkeypatch):
    # roles/app.yml: line 2 = install nginx (executed), line 5 = windows only (never ran)
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    body = (await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")).json()
    assert body["executed_lines"] == [2]
    assert body["never_run_lines"] == [5]   # the windows-only task, present but never executed


async def test_source_separates_skipped_from_executed_lines(authed_client, db, tmp_path, monkeypatch):
    """A when:false-skipped task got a task_start (so it's a real node) — it must show as SKIPPED,
    not 'executed' (purple) and not 'never run' (OV4). roles/app.yml: line2 ran, line5 skipped."""
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    # add the windows-only task (line 5) as a real node that SKIPPED
    db.add(RunNode(run_id=run.id, node_id="t2", parent_node_id="play-1", counter=5, depth=1,
                   node_type="task", name="windows only", status="skipped",
                   action="ansible.windows.win_package", task_path="roles/app.yml:5"))
    await db.commit()
    body = (await authed_client.get(f"/api/runs/{run.id}/nodes/t1/source")).json()
    assert body["executed_lines"] == [2]
    assert body["skipped_lines"] == [5]
    assert body["never_run_lines"] == []   # line 5 was reached-and-skipped, not never-run


async def test_tree_never_run_adds_ghost(authed_client, db, tmp_path, monkeypatch):
    src, sha = await _origin(tmp_path)
    run = await _seed(db, tmp_path, monkeypatch, sha=sha)
    # default tree: no ghosts
    base = (await authed_client.get(f"/api/runs/{run.id}/tree")).json()
    assert all(not n.get("never_run") for n in base["nodes"])
    # with never_run=1: the windows-only task (line 5) appears as a ghost off t1
    body = (await authed_client.get(f"/api/runs/{run.id}/tree?never_run=1")).json()
    ghosts = [n for n in body["nodes"] if n.get("never_run")]
    # NR1: a never-reached task is "never_run", NOT "skipped" (which means evaluated-and-skipped)
    assert len(ghosts) == 1 and ghosts[0]["label"] == "windows only" and ghosts[0]["status"] == "never_run"
    # the windows-only task HAS a `when:` so its condition is surfaced; a ghost with no static when
    # must carry no fabricated condition (NR1)
    assert ghosts[0]["condition"] == 'ansible_os_family == "Windows"' and ghosts[0]["is_conditional"] is True
    assert any(e["from"] == "t1" and e["to"] == ghosts[0]["id"] and e["branch"] == "never_run"
               for e in body["edges"])


async def test_never_run_ghost_without_when_has_no_condition(db, tmp_path, monkeypatch):
    """A never-reached task that has no `when:` must not be presented as a conditional decision (NR1).
    play.yml line 2 'a ran' executes; we make an unconditional task never-run by anchoring elsewhere."""
    from app.services.code_overlay import never_run_branches
    src, sha = await _origin(tmp_path)
    # prefix.yml line 2 'early never' has a when(line4); use block.yml 'inner one' (line7, NO when) instead
    run, objs = await _cloned_run_nodes(db, tmp_path, monkeypatch, sha=sha,
                                        nodes=[("outer", "block.yml:2"), ("tail", "block.yml:11")])
    ghosts, _edges = await never_run_branches(db, run, [objs["outer"], objs["tail"]])
    inner = next(g for g in ghosts if g.id == "nr:block.yml:7")  # 'inner one' — no when:
    assert inner.status == "never_run"
    assert inner.condition is None and inner.is_conditional is False


async def test_never_run_ghosts_anchor_to_nearest_preceding_executed(db, tmp_path, monkeypatch):
    """Each never-run ghost hangs off its nearest PRECEDING executed sibling by source line, so
    ghosts distribute across the flow (a tree) instead of all stemming from the first node."""
    from app.services.code_overlay import never_run_branches
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    src, sha = await _origin(tmp_path)
    gen = await _get_or_create_general(db)
    member = await _get_or_create_member(db, gen)
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git", status="cloned", organization_id=2)
    db.add(p); await db.flush()
    run = Run(source="awx", status="ok", owner_user_id=member.id, controller_id=c.id,
              project_id=19, scm_revision=sha)
    db.add(run); await db.flush()
    # a/c/e executed at play.yml lines 2/7/12; b(4) and d(9) are present but never executed.
    nodes = {}
    for nid, line in [("a", 2), ("c", 7), ("e", 12)]:
        n = RunNode(run_id=run.id, node_id=nid, parent_node_id="play-1", counter=line, depth=1,
                    node_type="task", name=f"{nid} ran", status="ok",
                    action="ansible.builtin.debug", task_path=f"play.yml:{line}")
        db.add(n); nodes[nid] = n
    await db.commit()
    await git.clone_or_fetch(str(src), project_repo_path(p.id), auth_type="none",
                             username=None, secret=None, max_bytes=10**9, timeout=60)

    ghosts, edges = await never_run_branches(db, run, [nodes["a"], nodes["c"], nodes["e"]])
    assert {g.id for g in ghosts} == {"nr:play.yml:4", "nr:play.yml:9"}
    anchor_of = {e.to: e.from_ for e in edges}
    # distribution: b(4) branches off a(2), d(9) off c(7) — NOT both off the first node a.
    assert anchor_of["nr:play.yml:4"] == "a"
    assert anchor_of["nr:play.yml:9"] == "c"


async def test_never_run_block_nests_children_under_ghost_block(db, tmp_path, monkeypatch):
    """A wholly-never-run `block:` becomes a ghost PARENT node; its children nest under it (chained
    in source order), and the block itself branches off the nearest preceding executed task."""
    from app.services.code_overlay import never_run_branches
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    src, sha = await _origin(tmp_path)
    gen = await _get_or_create_general(db)
    member = await _get_or_create_member(db, gen)
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git", status="cloned", organization_id=2)
    db.add(p); await db.flush()
    run = Run(source="awx", status="ok", owner_user_id=member.id, controller_id=c.id,
              project_id=19, scm_revision=sha)
    db.add(run); await db.flush()
    # outer (line 2) and tail (line 11) executed; the block (4) + inner one/two (7/9) never ran.
    nodes = {}
    for nid, line in [("outer", 2), ("tail", 11)]:
        n = RunNode(run_id=run.id, node_id=nid, parent_node_id="play-1", counter=line, depth=1,
                    node_type="task", name=f"{nid} ran", status="ok",
                    action="ansible.builtin.debug", task_path=f"block.yml:{line}")
        db.add(n); nodes[nid] = n
    await db.commit()
    await git.clone_or_fetch(str(src), project_repo_path(p.id), auth_type="none",
                             username=None, secret=None, max_bytes=10**9, timeout=60)

    ghosts, edges = await never_run_branches(db, run, [nodes["outer"], nodes["tail"]])
    by_id = {g.id: g for g in ghosts}
    assert set(by_id) == {"nr:block.yml:4", "nr:block.yml:7", "nr:block.yml:9"}
    assert by_id["nr:block.yml:4"].type == "block"          # the block is a ghost PARENT
    assert by_id["nr:block.yml:7"].type == "task"
    edge_set = {(e.from_, e.to) for e in edges}
    assert ("outer", "nr:block.yml:4") in edge_set          # block branches off the executed task
    assert ("nr:block.yml:4", "nr:block.yml:7") in edge_set  # first child nests under the block
    assert ("nr:block.yml:7", "nr:block.yml:9") in edge_set  # second child chains under the block
    # tail (line 11, executed) is never a ghost
    assert not any(g.id == "nr:block.yml:11" for g in ghosts)


async def _cloned_run_nodes(db, tmp_path, monkeypatch, *, sha, nodes):
    """Helper: cloned project + AWX run + the given executed RunNodes [(node_id, task_path)].
    Returns (run, {node_id: RunNode})."""
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "data"))
    gen = await _get_or_create_general(db)
    member = await _get_or_create_member(db, gen)
    c = AwxController(name=f"c-{uuid.uuid4()}", base_url="https://awx.test",
                      auth_token_encrypted=encrypt_token("t"))
    db.add(c); await db.flush()
    db.add(ControllerTeam(controller_id=c.id, team_id=gen.id, awx_organization_id=None))
    p = Project(controller_id=c.id, awx_project_id=19, name="day2", scm_type="git",
                scm_url="https://git.test/day2.git", status="cloned", organization_id=2)
    db.add(p); await db.flush()
    run = Run(source="awx", status="ok", owner_user_id=member.id, controller_id=c.id,
              project_id=19, scm_revision=sha)
    db.add(run); await db.flush()
    objs = {}
    for nid, tp in nodes:
        n = RunNode(run_id=run.id, node_id=nid, parent_node_id="play-1", counter=int(tp.split(":")[1]),
                    depth=1, node_type="task", name=nid, status="ok",
                    action="ansible.builtin.debug", task_path=tp)
        db.add(n); objs[nid] = n
    await db.commit()
    await git.clone_or_fetch(str(tmp_path / "origin"), project_repo_path(p.id), auth_type="none",
                             username=None, secret=None, max_bytes=10**9, timeout=60)
    return run, objs


async def test_static_import_line_not_never_run_or_ghost(db, tmp_path, monkeypatch):
    """A static import_tasks line is pre-expanded (no runner event for the directive line) — it must
    NOT be greyed as never-run nor spawn a ghost (OV3). import.yml: line 2 inline ran, line 5 import."""
    from app.services.code_overlay import build_node_source, never_run_branches
    src, sha = await _origin(tmp_path)
    run, objs = await _cloned_run_nodes(db, tmp_path, monkeypatch, sha=sha,
                                        nodes=[("inline", "import.yml:2")])
    body = await build_node_source(db, run, objs["inline"])
    assert body.executed_lines == [2]
    assert 4 not in body.never_run_lines       # the import_tasks task (line 4) is not "never run"
    ghosts, _edges = await never_run_branches(db, run, [objs["inline"]])
    assert not any(g.id == "nr:import.yml:4" for g in ghosts)   # and spawns no ghost


async def test_skipped_include_surfaces_target_file_ghosts(db, tmp_path, monkeypatch):
    """A skipped include_tasks → the target file's tasks appear as ghosts hanging off the include
    node, so a wholly-never-run include is visible road-not-taken (NR2)."""
    from app.services.code_overlay import never_run_branches
    src, sha = await _origin(tmp_path)
    run, objs = await _cloned_run_nodes(db, tmp_path, monkeypatch, sha=sha,
                                        nodes=[("ranhere", "including.yml:2"), ("incl", "including.yml:4")])
    ghosts, edges = await never_run_branches(db, run, [objs["ranhere"], objs["incl"]])
    gids = {g.id for g in ghosts}
    assert "nr:included.yml:1" in gids and "nr:included.yml:3" in gids   # target tasks as ghosts
    edge_set = {(e.from_, e.to) for e in edges}
    assert ("incl", "nr:included.yml:1") in edge_set                     # off the include node
    assert ("nr:included.yml:1", "nr:included.yml:3") in edge_set        # chained in source order


async def test_never_run_ghost_does_not_anchor_across_plays(db, tmp_path, monkeypatch):
    """A never-run task in a play with no executed tasks must NOT anchor to another play's task in
    the same file (NR4). 'deploy' (play web) ran; 'migrate' (play db, never entered) must not hang
    off deploy."""
    from app.services.code_overlay import never_run_branches
    src, sha = await _origin(tmp_path)
    run, objs = await _cloned_run_nodes(db, tmp_path, monkeypatch, sha=sha,
                                        nodes=[("deploy", "multiplay.yml:3")])
    ghosts, edges = await never_run_branches(db, run, [objs["deploy"]])
    edge_set = {(e.from_, e.to) for e in edges}
    assert ("deploy", "nr:multiplay.yml:7") not in edge_set   # no cross-play anchor
    # migrate's play (db) had no executed task → it isn't anchored here at all
    assert not any(e.to == "nr:multiplay.yml:7" for e in edges)


async def test_prefix_ghost_leads_into_first_executed(db, tmp_path, monkeypatch):
    """A ghost before the first executed task LEADS INTO it (edge ghost->executed), not the
    reverse — so it isn't drawn branching off a task that comes after it."""
    from app.services.code_overlay import never_run_branches
    src, sha = await _origin(tmp_path)
    run, objs = await _cloned_run_nodes(db, tmp_path, monkeypatch, sha=sha,
                                        nodes=[("late", "prefix.yml:5")])
    ghosts, edges = await never_run_branches(db, run, [objs["late"]])
    assert {g.id for g in ghosts} == {"nr:prefix.yml:2"}
    edge_set = {(e.from_, e.to) for e in edges}
    assert ("nr:prefix.yml:2", "late") in edge_set        # ghost leads INTO the executed task
    assert ("late", "nr:prefix.yml:2") not in edge_set     # NOT branching off a later task


async def test_rescue_always_render_as_separate_sections(db, tmp_path, monkeypatch):
    """A wholly-never-run block fans into separate block/rescue/always sub-branches, and the
    rescue/always ghosts are labelled with their section."""
    from app.services.code_overlay import never_run_branches
    src, sha = await _origin(tmp_path)
    run, objs = await _cloned_run_nodes(db, tmp_path, monkeypatch, sha=sha,
                                        nodes=[("ranfirst", "rescue.yml:2")])
    ghosts, edges = await never_run_branches(db, run, [objs["ranfirst"]])
    by_id = {g.id: g for g in ghosts}
    assert by_id["nr:rescue.yml:4"].type == "block"
    edge_set = {(e.from_, e.to) for e in edges}
    assert ("ranfirst", "nr:rescue.yml:4") in edge_set            # block branches off executed task
    # block fans into THREE separate sub-branches (body / rescue / always) directly off the block
    assert ("nr:rescue.yml:4", "nr:rescue.yml:7") in edge_set     # block section
    assert ("nr:rescue.yml:4", "nr:rescue.yml:10") in edge_set    # rescue section
    assert ("nr:rescue.yml:4", "nr:rescue.yml:13") in edge_set    # always section
    assert by_id["nr:rescue.yml:10"].sub.startswith("rescue:")
    assert by_id["nr:rescue.yml:13"].sub.startswith("always:")
