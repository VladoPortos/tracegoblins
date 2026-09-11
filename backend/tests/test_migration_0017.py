from pathlib import Path


VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def test_migration_0017_adds_upload_size_accounting():
    source = (VERSIONS / "0017_upload_quotas.py").read_text(encoding="utf-8")
    assert 'down_revision = "0016"' in source
    assert '"upload_size_bytes"' in source
    assert "octet_length(run_raw.content)" in source
    assert 'op.add_column("runs"' in source
    assert 'op.drop_column("runs", "upload_size_bytes")' in source
