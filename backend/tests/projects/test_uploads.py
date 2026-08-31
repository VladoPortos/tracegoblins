import os

import pytest

from app.projects import uploads
from app.projects.uploads import UploadError


async def test_save_preserves_structure_and_lists(tmp_path):
    base = tmp_path / "uploads"
    n = uploads.save_uploads(base, [
        ("playbook.yml", b"- hosts: all\n"),
        ("roles/app/tasks/main.yml", b"v1\n"),
    ], max_bytes=10_000, max_files=100)
    assert n == 2
    root = uploads.list_uploads_tree(base, "")
    names = {(e.name, e.type) for e in root}
    assert ("playbook.yml", "blob") in names and ("roles", "tree") in names
    sub = uploads.list_uploads_tree(base, "roles/app/tasks")
    assert [e.name for e in sub] == ["main.yml"]
    blob = uploads.read_upload_blob(base, "roles/app/tasks/main.yml", 10_000)
    assert blob.text == "v1\n"


async def test_missing_dir_lists_empty(tmp_path):
    assert uploads.list_uploads_tree(tmp_path / "nope", "") == []


async def test_traversal_rejected(tmp_path):
    base = tmp_path / "uploads"
    with pytest.raises(UploadError):
        uploads.save_uploads(base, [("../evil.yml", b"x")], max_bytes=1000, max_files=10)


async def test_caps_enforced(tmp_path):
    base = tmp_path / "uploads"
    with pytest.raises(UploadError):
        uploads.save_uploads(base, [("a", b"x"), ("b", b"y")], max_bytes=1000, max_files=1)
    with pytest.raises(UploadError):
        uploads.save_uploads(base, [("a", b"x" * 50)], max_bytes=10, max_files=10)


def test_save_uploads_rolls_back_all_files_when_promotion_fails(tmp_path, monkeypatch):
    base = tmp_path / "uploads"
    base.mkdir()
    (base / "existing.yml").write_bytes(b"old")

    real_replace = os.replace
    calls = 0

    def fail_second_file_promotion(src, dst):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated disk failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_second_file_promotion)

    with pytest.raises(UploadError, match="simulated disk failure"):
        uploads.save_uploads(
            base,
            [("existing.yml", b"new"), ("added.yml", b"added")],
            max_bytes=1000,
            max_files=10,
        )

    assert (base / "existing.yml").read_bytes() == b"old"
    assert not (base / "added.yml").exists()
    assert not list(base.glob(".tg-upload-*"))
    assert not list(base.glob(".tg-backup-*"))


def test_save_uploads_rejects_file_over_existing_directory_without_changes(tmp_path):
    base = tmp_path / "uploads"
    existing = base / "roles"
    existing.mkdir(parents=True)
    (existing / "main.yml").write_bytes(b"keep")

    with pytest.raises(UploadError, match="not a regular file"):
        uploads.save_uploads(
            base, [("roles", b"replacement")], max_bytes=1000, max_files=10,
        )

    assert existing.is_dir()
    assert (existing / "main.yml").read_bytes() == b"keep"
