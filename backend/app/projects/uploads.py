from __future__ import annotations

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
        targets.append((dest, data))
    for dest, data in targets:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
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
