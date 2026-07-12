from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.projects.git import BlobContent, TreeEntry
from app.projects.storage import safe_join


class UploadError(Exception):
    """Traversal / cap violation while writing or reading uploaded files."""


def save_uploads(uploads_dir: Path, files: list[tuple[str, bytes]], *,
                 max_bytes: int, max_files: int) -> int:
    """Write each (relpath, data) under `uploads_dir`, preserving structure. Traversal-validated
    per file; total count + bytes capped. Raises UploadError on any violation BEFORE writing
    (so a bad batch never half-lands)."""
    if len(files) > max_files:
        raise UploadError(f"too many files ({len(files)} > {max_files})")
    total = sum(len(data) for _rel, data in files)
    if total > max_bytes:
        raise UploadError(f"upload too large ({total} > {max_bytes} bytes)")
    targets: list[tuple[Path, bytes]] = []
    for relpath, data in files:
        try:
            dest = safe_join(uploads_dir, relpath)
        except ValueError as e:
            raise UploadError(f"rejected path {relpath!r}: {e}") from e
        if dest == uploads_dir.resolve():
            raise UploadError(f"rejected path {relpath!r}: empty")
        if dest.exists() and not dest.is_file():
            raise UploadError(f"rejected path {relpath!r}: destination is not a regular file")
        targets.append((dest, data))
    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path | None] = {}
    installed: set[Path] = set()
    try:
        # Stage the complete batch before changing any destination file.
        for dest, data in targets:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, raw_temp = tempfile.mkstemp(prefix=".tg-upload-", dir=dest.parent)
            temp = Path(raw_temp)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                temp.unlink(missing_ok=True)
                raise
            staged.append((dest, temp))

        # Promote staged files. Keep one backup per destination so duplicate paths retain
        # the historical last-write-wins behavior while rollback still restores the original.
        for dest, temp in staged:
            if dest not in backups:
                backup: Path | None = None
                if dest.exists():
                    fd, raw_backup = tempfile.mkstemp(prefix=".tg-backup-", dir=dest.parent)
                    os.close(fd)
                    backup = Path(raw_backup)
                    backup.unlink()
                    os.replace(dest, backup)
                backups[dest] = backup
            os.replace(temp, dest)
            installed.add(dest)
    except OSError as exc:
        rollback_error: OSError | None = None
        for _dest, temp in staged:
            temp.unlink(missing_ok=True)
        for dest in installed:
            try:
                dest.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_error = rollback_error or rollback_exc
        for dest, backup in backups.items():
            if backup is not None and backup.exists():
                try:
                    os.replace(backup, dest)
                except OSError as rollback_exc:
                    rollback_error = rollback_error or rollback_exc
        if rollback_error is not None:
            raise UploadError(
                f"upload storage failed: {exc}; rollback failed: {rollback_error}"
            ) from exc
        raise UploadError(f"upload storage failed: {exc}") from exc
    else:
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)
    return len(targets)


def list_uploads_tree(uploads_dir: Path, path: str) -> list[TreeEntry]:
    """Children directly under `path` in the uploads dir. Empty list if the dir is absent."""
    try:
        target = safe_join(uploads_dir, path)
    except ValueError as e:
        raise UploadError(str(e)) from e
    if not target.is_dir():
        return []
    entries: list[TreeEntry] = []
    for child in target.iterdir():
        is_dir = child.is_dir()
        entries.append(TreeEntry(
            name=child.name,
            type="tree" if is_dir else "blob",
            size=None if is_dir else child.stat().st_size,
            mode="040000" if is_dir else "100644",
        ))
    entries.sort(key=lambda e: (e.type != "tree", e.name.lower()))
    return entries


def read_upload_blob(uploads_dir: Path, path: str, max_bytes: int) -> BlobContent:
    """File contents under the uploads dir, capped (matches git.read_blob semantics)."""
    try:
        target = safe_join(uploads_dir, path)
    except ValueError as e:
        raise UploadError(str(e)) from e
    if not target.is_file():
        raise UploadError(f"not a file: {path!r}")
    size = target.stat().st_size
    if size > max_bytes:
        return BlobContent(text=None, size=size, too_large=True, binary=False)
    raw = target.read_bytes()
    if b"\x00" in raw:
        return BlobContent(text=None, size=size, too_large=False, binary=True)
    return BlobContent(text=raw.decode("utf-8", "replace"), size=size, too_large=False, binary=False)
