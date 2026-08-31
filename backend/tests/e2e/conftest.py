import os

import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("E2E_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {**browser_type_launch_args, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}


@pytest.fixture
def browser_context_args(browser_context_args, base_url):
    return {**browser_context_args, "base_url": base_url, "ignore_https_errors": True}


# Shared-DB e2e run order (lower = earlier). Exposed as a module constant so it can be
# asserted directly (test_kb_order.py). Invariants:
#   - onboarding owns the ONE-SHOT /setup wizard (D7) -> must run first.
#   - upload ends asserting the admin's "My logs" is empty ("No logs yet"); collaboration
#     and kb both leave runs owned by the SAME admin -> they must run AFTER upload.
#   - kb uploads runs AND promotes a GLOBAL signature -> run it after clean-slate flows.
#   - Path consumes the synced job and must run before 2FA mutates the shared admin account.
#   - 2FA is the final stateful browser flow.
E2E_FILE_ORDER = {
    "test_onboarding_flow.py": 0,
    "test_upload_status_map.py": 1,
    "test_logs_view.py": 2,
    "test_collaboration.py": 3,
    "test_awx_sync.py": 4,
    "test_projects.py": 5,   # depends on synced mock controller/runs from test_awx_sync
    "test_path_view.py": 6,  # depends on synced mock job 743
    "test_kb.py": 7,
    "test_2fa.py": 8,
}


def pytest_collection_modifyitems(items):
    items.sort(
        key=lambda it: next(
            (v for k, v in E2E_FILE_ORDER.items() if k in str(it.fspath)), 99
        )
    )
