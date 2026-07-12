from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# ref = a 7–40 hex SHA, "HEAD", or a conservative branch name (no shell metachars, no "..",
# no leading "-"/"/"). path = relative, no "..", no leading "/", no NUL.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


class GitError(Exception):
    """Any git-subprocess / validation failure (nonzero exit, timeout, bad ref/path)."""


@dataclass(frozen=True)
class TreeEntry:
    name: str
    type: str  # "blob" | "tree"
    size: int | None
    mode: str


@dataclass(frozen=True)
class BlobContent:
    text: str | None
    size: int
    too_large: bool
    binary: bool


def is_clonable_git_url(url: str | None) -> bool:
    """HTTPS-only allow-list. Rejects http/ssh/git/file and anything unparseable (SSRF posture
    §9: this app fetches internal git on purpose, so we constrain by SCHEME + list-arg exec +
    GIT_ASKPASS, not by blocking private IPs)."""
    if not url:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and not parts.username
        and not parts.password
        and bool(parts.hostname)
    )


def _validate_ref(ref: str) -> str:
    if _SHA_RE.match(ref) or ref == "HEAD" or _BRANCH_RE.match(ref):
        if ".." not in ref:
            return ref
    raise GitError(f"invalid ref: {ref!r}")


def _validate_path(path: str) -> str:
    if path.startswith("/") or "\x00" in path or ".." in path.split("/"):
        raise GitError(f"invalid path: {path!r}")
    return path


async def _git(*args: str, cwd: Path | None = None, env: dict | None = None,
               timeout: int = 60, watch_path: Path | None = None,
               max_bytes: int | None = None) -> bytes:
    """Run `git <args>` with list-args (no shell), returning stdout bytes. Raises GitError on
    nonzero exit or timeout. A minimal env (PATH + GIT_TERMINAL_PROMPT=0 + caller extras) keeps
    git from ever blocking on an interactive credential prompt."""
    base_env = {"PATH": os.environ.get("PATH", ""), "GIT_TERMINAL_PROMPT": "0",
                "HOME": os.environ.get("HOME", "/tmp")}
    if env:
        base_env.update(env)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd) if cwd else None, env=base_env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise GitError("git binary not found") from e
    communicate = asyncio.create_task(proc.communicate())
    deadline = asyncio.get_running_loop().time() + timeout
    while not communicate.done():
        if watch_path is not None and max_bytes is not None and _dir_size(watch_path) > max_bytes:
            proc.kill()
            await communicate
            raise GitError(f"git repository exceeded size cap ({max_bytes} bytes)")
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            proc.kill()
            await communicate
            raise GitError(f"git timed out after {timeout}s")
        await asyncio.wait({communicate}, timeout=min(0.05, remaining))
    out, err = communicate.result()
    if watch_path is not None and max_bytes is not None and _dir_size(watch_path) > max_bytes:
        raise GitError(f"git repository exceeded size cap ({max_bytes} bytes)")
    if proc.returncode != 0:
        raise GitError(err.decode("utf-8", "replace").strip() or f"git exit {proc.returncode}")
    return out


def _askpass_env(auth_type: str, username: str | None, secret: str | None) -> tuple[dict, str | None]:
    """Build the credential env + a temp GIT_ASKPASS helper script for token/userpass auth.

    Returns (env_additions, askpass_script_path_or_None). The secret is passed ONLY via env to
    a helper script git invokes — never in argv, the repo config, the reflog, or our logs.
    Caller must delete the returned script path when done.
    """
    if auth_type == "none" or not secret:
        return {}, None
    if auth_type == "token":
        # Pair the PAT with the supplied username when given (GitHub Enterprise / GitLab require
        # the real account username + PAT-as-password), else fall back to the github.com / app-
        # token convention. Sending "x-access-token" to GitHub Enterprise yields a 403
        # "Password authentication is not available", so the username field matters there.
        user = username or "x-access-token"
        password = secret
    else:                                # userpass
        user = username or ""
        password = secret
    fd, script_path = tempfile.mkstemp(prefix="tg-askpass-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(
            "#!/bin/sh\n"
            'case "$1" in\n'
            '  Username*) printf "%s" "$TG_GIT_USERNAME" ;;\n'
            '  *) printf "%s" "$TG_GIT_PASSWORD" ;;\n'
            "esac\n"
        )
    os.chmod(script_path, 0o700)
    env = {"GIT_ASKPASS": script_path, "TG_GIT_USERNAME": user, "TG_GIT_PASSWORD": password}
    return env, script_path


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


async def _snapshot_refs(repo_path: Path, timeout: int) -> dict[str, str]:
    out = await _git(
        "-C", str(repo_path), "for-each-ref", "--format=%(refname)%09%(objectname)",
        timeout=timeout,
    )
    refs: dict[str, str] = {}
    for line in out.decode("utf-8", "replace").splitlines():
        ref, sep, oid = line.partition("\t")
        if sep and ref and oid:
            refs[ref] = oid
    return refs


async def _restore_refs(repo_path: Path, refs: dict[str, str], timeout: int) -> None:
    current = await _snapshot_refs(repo_path, timeout)
    for ref in current.keys() - refs.keys():
        await _git("-C", str(repo_path), "update-ref", "-d", ref, timeout=timeout)
    for ref, oid in refs.items():
        if current.get(ref) != oid:
            await _git("-C", str(repo_path), "update-ref", ref, oid, timeout=timeout)


async def _discard_rejected_fetch(repo_path: Path, timeout: int) -> None:
    await _git(
        "-C", str(repo_path), "reflog", "expire", "--expire=now", "--all",
        timeout=timeout,
    )
    await _git("-C", str(repo_path), "gc", "--prune=now", timeout=timeout)


async def clone_or_fetch(source_url: str, repo_path: Path, *, auth_type: str,
                         username: str | None, secret: str | None,
                         max_bytes: int, timeout: int) -> tuple[int, str]:
    """Bare-clone `source_url` into `repo_path` (first time) or fetch updates (subsequent).

    Returns (clone_size_bytes, default_branch). Enforces a post-clone size cap (abort + raise
    GitError above max_bytes). Credentials flow through GIT_ASKPASS only.
    """
    env, askpass = _askpass_env(auth_type, username, secret)
    try:
        if (repo_path / "HEAD").exists():
            old_url = (await _git(
                "-C", str(repo_path), "remote", "get-url", "origin", timeout=timeout,
            )).decode().strip()
            old_refs = await _snapshot_refs(repo_path, timeout)
            # Re-point origin to the CURRENT url before fetching (GIT1): an edited git_url_override
            # would otherwise be silently ignored and we'd keep fetching the stale clone's remote.
            try:
                await _git("-C", str(repo_path), "remote", "set-url", "origin", source_url,
                           env=env, timeout=timeout)
                await _git(
                    "-C", str(repo_path), "fetch", "--all", "--prune", "--no-write-fetch-head",
                    env=env, timeout=timeout, watch_path=repo_path, max_bytes=max_bytes,
                )
                size = _dir_size(repo_path)
            except GitError as exc:
                try:
                    await _restore_refs(repo_path, old_refs, timeout)
                    await _git(
                        "-C", str(repo_path), "remote", "set-url", "origin", old_url,
                        timeout=timeout,
                    )
                    await _discard_rejected_fetch(repo_path, timeout)
                except GitError as rollback_exc:
                    raise GitError(f"{exc}; fetch rollback failed: {rollback_exc}") from exc
                raise
            if size > max_bytes:
                await _restore_refs(repo_path, old_refs, timeout)
                await _git(
                    "-C", str(repo_path), "remote", "set-url", "origin", old_url,
                    timeout=timeout,
                )
                await _discard_rejected_fetch(repo_path, timeout)
                # Do NOT destroy a previously-good clone over a remote-side overage (GIT2) — keep it
                # browsable and surface the error so the update is refused, not the project broken.
                raise GitError(f"fetched repo exceeds size cap ({size} > {max_bytes} bytes); "
                               "existing clone kept")
        else:
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                await _git(
                    "clone", "--bare", source_url, str(repo_path), env=env, timeout=timeout,
                    watch_path=repo_path, max_bytes=max_bytes,
                )
            except GitError:
                shutil.rmtree(repo_path, ignore_errors=True)
                raise
            size = _dir_size(repo_path)
            if size > max_bytes:
                shutil.rmtree(repo_path, ignore_errors=True)  # a partial/oversized first clone is worthless
                raise GitError(f"clone exceeds size cap ({size} > {max_bytes} bytes)")
        # default branch: bare clone sets HEAD → refs/heads/<default>
        try:
            head = (await _git("-C", str(repo_path), "symbolic-ref", "--short", "HEAD",
                               timeout=timeout)).decode().strip()
        except GitError:
            head = "HEAD"
        return size, head or "HEAD"
    finally:
        if askpass:
            try:
                os.unlink(askpass)
            except OSError:
                pass


async def list_tree(repo_path: Path, ref: str, path: str) -> list[TreeEntry]:
    """List entries directly under `path` at `ref` (read-only ls-tree, NUL-delimited)."""
    ref = _validate_ref(ref)
    path = _validate_path(path)
    spec = f"{path.rstrip('/')}/" if path else ""
    args = ["-C", str(repo_path), "ls-tree", "--long", "-z", ref]
    if spec:
        args += ["--", spec]
    out = await _git(*args)
    entries: list[TreeEntry] = []
    for record in out.split(b"\x00"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        parts = meta.decode().split()
        if len(parts) < 4:
            continue
        mode, otype, _obj, size_s = parts[0], parts[1], parts[2], parts[3]
        entries.append(TreeEntry(
            name=name.decode("utf-8", "replace").rstrip("/").rsplit("/", 1)[-1],
            type=otype,
            size=int(size_s) if size_s.isdigit() else None,
            mode=mode,
        ))
    entries.sort(key=lambda e: (e.type != "tree", e.name.lower()))
    return entries


async def read_blob(repo_path: Path, ref: str, path: str, max_bytes: int) -> BlobContent:
    """Return file contents at `ref:path`, capped at `max_bytes`. Oversized → too_large marker
    (size from cat-file -s, no read). Binary (NUL byte) → binary marker, no text."""
    ref = _validate_ref(ref)
    path = _validate_path(path)
    obj = f"{ref}:{path}"
    size = int((await _git("-C", str(repo_path), "cat-file", "-s", obj)).decode().strip() or "0")
    if size > max_bytes:
        return BlobContent(text=None, size=size, too_large=True, binary=False)
    raw = await _git("-C", str(repo_path), "cat-file", "blob", obj)
    if b"\x00" in raw:
        return BlobContent(text=None, size=size, too_large=False, binary=True)
    return BlobContent(text=raw.decode("utf-8", "replace"), size=size, too_large=False, binary=False)


async def revision_exists(repo_path: Path, ref: str) -> bool:
    """True iff `ref` resolves to an object in the bare clone (e.g. a run's scm_revision that
    has actually been fetched). Invalid/unknown ref → False (no raise)."""
    try:
        ref = _validate_ref(ref)
    except GitError:
        return False
    try:
        await _git("-C", str(repo_path), "cat-file", "-t", ref)
        return True
    except GitError:
        return False
