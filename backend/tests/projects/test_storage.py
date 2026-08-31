import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.projects import storage


def test_repo_and_uploads_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_data_dir", str(tmp_path / "projects"))
    pid = uuid.uuid4()
    assert storage.project_repo_path(pid) == tmp_path / "projects" / str(pid) / "repo.git"
    assert storage.project_uploads_path(pid) == tmp_path / "projects" / str(pid) / "uploads"


def test_safe_join_allows_nested(tmp_path):
    base = tmp_path
    assert storage.safe_join(base, "a/b/c.yml") == (base / "a/b/c.yml").resolve()
    assert storage.safe_join(base, "") == base.resolve()


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "a/../../b", "x\x00y"])
def test_safe_join_rejects_traversal(tmp_path, bad):
    with pytest.raises(ValueError):
        storage.safe_join(tmp_path, bad)
