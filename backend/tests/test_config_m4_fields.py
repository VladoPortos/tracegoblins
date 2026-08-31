import pytest
from pydantic import ValidationError

from app.core.config import Settings, validate_runtime_secrets


def test_samesite_none_requires_secure_in_any_env():
    # CONFIG1: SameSite=None without Secure → browsers drop all cookies → must fail fast everywhere
    s = Settings(environment="development", cookie_samesite="none", cookie_secure=False)
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        validate_runtime_secrets(s)
    # the valid combo passes
    validate_runtime_secrets(Settings(environment="development", cookie_samesite="none", cookie_secure=True))
    validate_runtime_secrets(Settings(environment="development", cookie_samesite="lax", cookie_secure=False))


def test_retention_and_scheduler_defaults():
    s = Settings()
    assert s.retention_days == 90
    assert s.scheduler_enabled is True


def test_scheduler_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("RETENTION_DAYS", "0")
    s = Settings()
    assert s.scheduler_enabled is False
    assert s.retention_days == 0


@pytest.mark.parametrize("interval", [0, -1])
def test_project_refetch_interval_must_be_positive(interval):
    with pytest.raises(ValidationError, match="project_refetch_interval_minutes"):
        Settings(project_refetch_interval_minutes=interval)
