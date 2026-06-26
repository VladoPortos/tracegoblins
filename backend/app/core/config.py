from functools import lru_cache
from typing import ClassVar, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Database (async driver)
    database_url: str = Field("postgresql+asyncpg://tracegoblins:tracegoblins@localhost:5432/tracegoblins")

    # Crypto / signing
    secret_key: SecretStr = Field(SecretStr("change-me-in-prod"))
    token_enc_key: SecretStr = Field(SecretStr(""))  # AWX token encryption (M4)

    # Cookies / proxy
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"  # validated → no malformed Set-Cookie
    session_cookie_name: str = "tg_session"
    # CSRF cookie/header names are NOT env-overridable: the built-in React SPA hard-codes
    # 'csrf_token' / 'X-CSRF-Token' (frontend/src/api/client.ts) and has no channel to learn an
    # overridden name, so an env override would silently 403 every mutation. ClassVar keeps them
    # off the BaseSettings field set (no env binding) while still readable as settings.csrf_*.
    csrf_cookie_name: ClassVar[str] = "csrf_token"
    csrf_header_name: ClassVar[str] = "X-CSRF-Token"

    # Session TTLs
    session_idle_minutes: int = 120
    session_absolute_hours: int = 12
    session_remember_days: int = 30
    touch_throttle_seconds: int = 60
    mfa_pending_ttl_minutes: int = 5
    # Force admins to enrol 2FA before using the app (redirect-to-enroll, non-bricking).
    # Default on (secure); deployments/e2e may disable via MFA_ADMIN_REQUIRED=false.
    mfa_admin_required: bool = True

    # Invites
    invite_expire_hours: int = 72

    # Login rate limiting
    login_max_attempts: int = 5
    login_window_seconds: int = 300
    login_lockout_seconds: int = 900

    # Headers
    csp_report_only: bool = False

    # Background scheduler (M4) — APScheduler in-process; one leader per cluster.
    scheduler_enabled: bool = True

    # Retention (M4) — delete source='awx' runs older than N days. 0 disables the sweep.
    retention_days: int = 90

    # Knowledge base (M5) — fuzzy pg_trgm match cutoff for KB signature matching.
    # Exact signature_key always wins; fuzzy hits below this similarity are ignored.
    kb_match_threshold: float = Field(0.35)

    # Projects subsystem (M2) — local git-clone + upload storage on the appdata volume.
    projects_data_dir: str = "/app/data/projects"
    git_clone_max_bytes: int = 500 * 1024 * 1024       # abort clone + set status=error above this
    git_clone_timeout_seconds: int = 300               # clone/fetch subprocess timeout
    project_blob_max_bytes: int = 2 * 1024 * 1024      # file-viewer cap; larger → "too large" marker
    project_upload_max_bytes: int = 50 * 1024 * 1024   # total bytes per upload request
    project_upload_max_files: int = 2000               # max parts per upload request
    project_refetch_interval_minutes: int = 1440       # periodic git re-fetch for cloned projects (daily)

    # App
    app_name: str = "Tracegoblins"
    environment: str = "production"
    app_static_dir: str = "/app/frontend/dist"

    @property
    def secret(self) -> str:
        return self.secret_key.get_secret_value()

    @property
    def token_enc(self) -> str:
        return self.token_enc_key.get_secret_value()


_INSECURE_SECRET_KEY = "change-me-in-prod"


def validate_runtime_secrets(s: "Settings") -> None:
    """Fail fast at startup if a production deployment is missing critical secrets.

    Only enforced when ``environment == 'production'`` so dev/test keep working on defaults.
    Catches the two footguns: the placeholder SECRET_KEY (forgeable sessions/CSRF) and an
    empty TOKEN_ENC_KEY (AWX-token encryption would otherwise only blow up later, on first use).
    """
    if s.environment != "production":
        return
    problems: list[str] = []
    if not s.secret or s.secret == _INSECURE_SECRET_KEY:
        problems.append("SECRET_KEY must be set to a strong random value")
    if not s.token_enc:
        problems.append("TOKEN_ENC_KEY must be set (a Fernet key) to encrypt AWX tokens")
    if problems:
        raise RuntimeError(
            "Refusing to start with an insecure production configuration: "
            + "; ".join(problems)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
