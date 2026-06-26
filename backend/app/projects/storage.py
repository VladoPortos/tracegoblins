from __future__ import annotations

import uuid
from pathlib import Path

from app.core.config import settings


def projects_root() -> Path:
    """The base directory holding all per-project storage (on the `appdata` volume)."""
    return Path(settings.projects_data_dir)


def project_repo_path(project_id: uuid.UUID | str) -> Path:
    """Bare git clone directory for a project — holds every fetched revision."""
    return projects_root() / str(project_id) / "repo.git"


def project_uploads_path(project_id: uuid.UUID | str) -> Path:
    """Drop-zone uploads directory for a project (structure preserved)."""
    return projects_root() / str(project_id) / "uploads"


def safe_join(base: Path, relpath: str) -> Path:
    """Resolve ``base / relpath``, rejecting absolute paths, NUL bytes, and ``..`` traversal.

    Returns the resolved path (which is ``base`` itself for an empty relpath). Raises
    ``ValueError`` if the result would escape ``base`` — the single guard for every
    tree/blob/upload path that comes from a client.
    """
    if relpath.startswith("/") or "\x00" in relpath:
        raise ValueError("absolute or null path rejected")
    base_resolved = base.resolve()
    candidate = (base / relpath).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise ValueError("path traversal rejected")
    return candidate
