import asyncio
import os
import shutil
import stat
from pathlib import Path

import pytest

from app.projects import git

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git binary not on PATH")


async def _run(*args, cwd=None):
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, err.decode()
    return out.decode()


@pytest.fixture
async def origin(tmp_path):
    """A local git repo with two commits; returns (path, first_sha, second_sha)."""
    src = tmp_path / "origin"
    src.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    await _run("git", "init", "-q", "-b", "main", str(src))
    (src / "site.yml").write_text("- hosts: all\n")
    (src / "roles").mkdir()
    (src / "roles" / "main.yml").write_text("v1\n")
    proc = await asyncio.create_subprocess_exec("git", "-C", str(src), "add", "-A", env=env)
    await proc.communicate()
    proc = await asyncio.create_subprocess_exec("git", "-C", str(src), "commit", "-q", "-m", "c1", env=env)
    await proc.communicate()
    first = (await _run("git", "-C", str(src), "rev-parse", "HEAD")).strip()
    (src / "roles" / "main.yml").write_text("v2 changed\n")
    proc = await asyncio.create_subprocess_exec("git", "-C", str(src), "commit", "-aqm", "c2", env=env)
    await proc.communicate()
    second = (await _run("git", "-C", str(src), "rev-parse", "HEAD")).strip()
    return src, first, second


def test_is_clonable_git_url():
    assert git.is_clonable_git_url("https://github.com/x/y.git") is True
    assert git.is_clonable_git_url("http://insecure/x.git") is False
    assert git.is_clonable_git_url("git@github.com:x/y.git") is False
    assert git.is_clonable_git_url("ssh://git@host/x.git") is False
    assert git.is_clonable_git_url("file:///etc") is False
    assert git.is_clonable_git_url(None) is False
    assert git.is_clonable_git_url("https://user:pass@github.com/x/y.git") is False
    assert git.is_clonable_git_url("https://token@github.com/x/y.git") is False
    assert git.is_clonable_git_url("https://github.com:443/x/y.git") is True   # port is fine


def test_dir_size_ignores_file_deleted_during_scan(tmp_path, monkeypatch):
    stable = tmp_path / "stable.pack"
    stable.write_bytes(b"stable")
    vanishing = tmp_path / "packed-refs.new"
    vanishing.write_bytes(b"temporary")
    real_stat = Path.stat
    vanishing_stat_calls = 0

    def stat_with_git_race(path, *args, **kwargs):
        nonlocal vanishing_stat_calls
        if path == vanishing:
            vanishing_stat_calls += 1
            if vanishing_stat_calls == 2:
                raise FileNotFoundError(path)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_git_race)

    assert git._dir_size(tmp_path) == len(b"stable")


async def test_clone_then_browse_per_revision(origin, tmp_path):
    src, first, second = origin
    repo = tmp_path / "clone" / "repo.git"
    size, branch = await git.clone_or_fetch(
        str(src), repo, auth_type="none", username=None, secret=None,
        max_bytes=500 * 1024 * 1024, timeout=60,
    )
    assert size > 0 and branch == "main"

    # tree at HEAD (default branch ref)
    root = await git.list_tree(repo, "HEAD", "")
    names = {e.name for e in root}
    assert {"site.yml", "roles"} <= names
    roles = [e for e in root if e.name == "roles"][0]
    assert roles.type == "tree"

    # per-revision browse: roles/main.yml differs between the two commits
    b_second = await git.read_blob(repo, second, "roles/main.yml", 2 * 1024 * 1024)
    assert b_second.text == "v2 changed\n" and b_second.binary is False and b_second.too_large is False
    b_first = await git.read_blob(repo, first, "roles/main.yml", 2 * 1024 * 1024)
    assert b_first.text == "v1\n"

    assert await git.revision_exists(repo, second) is True
    assert await git.revision_exists(repo, "f" * 40) is False


async def test_traversal_and_cap(origin, tmp_path):
    src, first, second = origin
    repo = tmp_path / "clone" / "repo.git"
    await git.clone_or_fetch(str(src), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    with pytest.raises(git.GitError):
        await git.list_tree(repo, "HEAD", "../escape")
    with pytest.raises(git.GitError):
        await git.read_blob(repo, "HEAD", "/etc/passwd", 1024)
    # blob cap: 1-byte cap on a 9+ byte file → too_large marker, no text
    capped = await git.read_blob(repo, "HEAD", "site.yml", 1)
    assert capped.too_large is True and capped.text is None


async def test_clone_then_fetch_existing(origin, tmp_path):
    """Second call on an existing bare clone takes the fetch branch, not the clone branch."""
    src, first, second = origin
    repo = tmp_path / "clone" / "repo.git"
    size1, branch1 = await git.clone_or_fetch(
        str(src), repo, auth_type="none", username=None, secret=None,
        max_bytes=500 * 1024 * 1024, timeout=60,
    )
    assert size1 > 0 and branch1 == "main"
    # repo already exists → fetch path
    size2, branch2 = await git.clone_or_fetch(
        str(src), repo, auth_type="none", username=None, secret=None,
        max_bytes=500 * 1024 * 1024, timeout=60,
    )
    assert size2 > 0 and branch2 == "main"


async def test_fetch_repoints_remote_to_current_url(origin, tmp_path):
    """GIT1: after the URL changes (git_url_override edited), a re-fetch must pull from the NEW url,
    not the stale origin baked in at clone time."""
    src_a, _f, _s = origin
    # a second origin with a DISTINCT file the first one doesn't have
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]}
    src_b = tmp_path / "origin_b"; src_b.mkdir()
    await _run("git", "init", "-q", "-b", "main", str(src_b))
    (src_b / "ONLY_IN_B.txt").write_text("hello from B\n")
    p = await asyncio.create_subprocess_exec("git", "-C", str(src_b), "add", "-A", env=env); await p.communicate()
    p = await asyncio.create_subprocess_exec("git", "-C", str(src_b), "commit", "-qm", "b1", env=env); await p.communicate()
    b_head = (await _run("git", "-C", str(src_b), "rev-parse", "HEAD")).strip()

    repo = tmp_path / "clone" / "repo.git"
    await git.clone_or_fetch(str(src_a), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    # URL changed → re-fetch from B; B's commit + file must now be readable
    await git.clone_or_fetch(str(src_b), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    blob = await git.read_blob(repo, b_head, "ONLY_IN_B.txt", 1 << 20)
    assert blob.text == "hello from B\n"


async def test_fetch_over_cap_keeps_existing_clone(origin, tmp_path):
    """GIT2: a refetch that exceeds the size cap must NOT destroy a previously-good clone."""
    src, _f, _s = origin
    repo = tmp_path / "clone" / "repo.git"
    await git.clone_or_fetch(str(src), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    assert (repo / "HEAD").exists()
    with pytest.raises(git.GitError):
        await git.clone_or_fetch(str(src), repo, auth_type="none", username=None, secret=None,
                                 max_bytes=1, timeout=60)   # absurd cap on refetch
    assert (repo / "HEAD").exists()   # the good clone survives — browsing still works


async def test_git_monitor_kills_process_when_repository_crosses_cap(tmp_path, monkeypatch):
    watch = tmp_path / "repo.git"
    watch.mkdir()

    class GrowingProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False

        async def communicate(self):
            (watch / "incoming.pack").write_bytes(b"x" * 32)
            await asyncio.sleep(0.1)
            if self.returncode is None:
                self.returncode = 0
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    proc = GrowingProcess()

    async def fake_create(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

    try:
        with pytest.raises(git.GitError, match="size cap"):
            await git._git("fetch", watch_path=watch, max_bytes=16)
    except TypeError as exc:
        pytest.fail(f"git subprocess has no live size boundary: {exc}")

    assert proc.killed is True


async def test_over_cap_fetch_restores_previous_head(origin, tmp_path):
    src, _first, _second = origin
    repo = tmp_path / "clone" / "repo.git"
    initial_size, _ = await git.clone_or_fetch(
        str(src), repo, auth_type="none", username=None, secret=None,
        max_bytes=500 * 1024 * 1024, timeout=60,
    )
    old_head = (await _run("git", "-C", str(repo), "rev-parse", "HEAD")).strip()

    (src / "large.bin").write_bytes(os.urandom(256 * 1024))
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ["PATH"],
    }
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(src), "add", "large.bin", env=env,
    )
    await proc.communicate()
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(src), "commit", "-qm", "large", env=env,
    )
    await proc.communicate()
    rejected_head = (await _run("git", "-C", str(src), "rev-parse", "HEAD")).strip()

    with pytest.raises(git.GitError, match="size cap"):
        await git.clone_or_fetch(
            str(src), repo, auth_type="none", username=None, secret=None,
            max_bytes=initial_size + 32 * 1024, timeout=60,
        )

    restored_head = (await _run("git", "-C", str(repo), "rev-parse", "HEAD")).strip()
    assert restored_head == old_head
    assert await git.revision_exists(repo, rejected_head) is False


def test_askpass_env_creates_secure_script():
    """token auth → GIT_ASKPASS points at an existing 0o700 helper; secret only in env."""
    env, script = git._askpass_env("token", None, "s3cr3t-token")
    try:
        assert script is not None
        assert env["GIT_ASKPASS"] == script
        assert os.path.exists(script)
        mode = stat.S_IMODE(os.stat(script).st_mode)
        if os.name != "nt":  # Windows does not expose POSIX chmod bits; production is Linux.
            assert mode == 0o700
        assert env["TG_GIT_PASSWORD"] == "s3cr3t-token"
        assert env["TG_GIT_USERNAME"] == "x-access-token"
    finally:
        if script:
            os.unlink(script)


def test_askpass_env_token_uses_supplied_username():
    """token auth WITH a username → uses it (GitHub Enterprise needs username + PAT)."""
    env, script = git._askpass_env("token", "alice", "s3cr3t-token")
    try:
        assert env["TG_GIT_USERNAME"] == "alice"
        assert env["TG_GIT_PASSWORD"] == "s3cr3t-token"
    finally:
        if script:
            os.unlink(script)


def test_askpass_env_none_no_script():
    env, script = git._askpass_env("none", None, None)
    assert env == {} and script is None


async def test_binary_blob(tmp_path):
    src = tmp_path / "binorigin"
    src.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]}
    await _run("git", "init", "-q", "-b", "main", str(src))
    (src / "blob.bin").write_bytes(b"abc\x00def")
    proc = await asyncio.create_subprocess_exec("git", "-C", str(src), "add", "-A", env=env)
    await proc.communicate()
    proc = await asyncio.create_subprocess_exec("git", "-C", str(src), "commit", "-q", "-m", "c1", env=env)
    await proc.communicate()

    repo = tmp_path / "clone" / "bin.git"
    await git.clone_or_fetch(str(src), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    b = await git.read_blob(repo, "HEAD", "blob.bin", 2 * 1024 * 1024)
    assert b.binary is True and b.text is None and b.too_large is False


async def test_nul_in_path_rejected(origin, tmp_path):
    src, first, second = origin
    repo = tmp_path / "clone" / "repo.git"
    await git.clone_or_fetch(str(src), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    with pytest.raises(git.GitError):
        await git.read_blob(repo, "HEAD", "a\x00b", 1024)


async def test_revision_exists_invalid_format(origin, tmp_path):
    src, first, second = origin
    repo = tmp_path / "clone" / "repo.git"
    await git.clone_or_fetch(str(src), repo, auth_type="none", username=None, secret=None,
                             max_bytes=500 * 1024 * 1024, timeout=60)
    # invalid-format ref → False (no raise), distinct from valid-format-but-unknown SHA
    assert await git.revision_exists(repo, "not a ref!") is False
    assert await git.revision_exists(repo, "f" * 40) is False
