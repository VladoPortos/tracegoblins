from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
OVERRIDE = ROOT / "docker-compose.e2e.yml"


def test_override_adds_mock_awx_sidecar_and_pins_e2e_env():
    data = yaml.safe_load(OVERRIDE.read_text())
    svc = data["services"]
    assert "mock-awx" in svc, "E2E override must add a mock-awx sidecar"
    mock = svc["mock-awx"]
    assert "uvicorn" in " ".join(mock["command"]) if isinstance(mock["command"], list) else "uvicorn" in mock["command"]
    assert "tests.e2e.mock_awx_server:app" in (
        " ".join(mock["command"]) if isinstance(mock["command"], list) else mock["command"]
    )
    # app is pinned for E2E
    app_env = svc["app"]["environment"]
    assert app_env["COOKIE_SECURE"] in ("false", False)
    assert app_env["SCHEDULER_ENABLED"] in ("false", False)
    assert app_env.get("TOKEN_ENC_KEY")  # a fixed Fernet key for the run


def test_override_does_not_publish_db_port():
    # security-first: the prod compose never publishes :5432; the override mustn't either.
    data = yaml.safe_load(OVERRIDE.read_text())
    db = data["services"].get("db", {})
    assert "ports" not in db
