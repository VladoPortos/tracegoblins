import importlib

import pytest

pytestmark = pytest.mark.e2e


def test_kb_file_is_pinned_last_in_e2e_order():
    # The shared-DB e2e order map (conftest.pytest_collection_modifyitems closure) must
    # rank test_kb.py AFTER onboarding/upload/collaboration/awx_sync so the KB flow — which
    # uploads runs and promotes a GLOBAL signature — never perturbs an earlier file's
    # "No logs yet" / clean-slate assertions on the single shared database.
    conftest = importlib.import_module("tests.e2e.conftest")
    order = conftest.E2E_FILE_ORDER
    assert order["test_kb.py"] > order["test_awx_sync.py"]
    assert order["test_kb.py"] > order["test_collaboration.py"]
    assert order["test_kb.py"] > order["test_upload_status_map.py"]
    assert order["test_kb.py"] > order["test_onboarding_flow.py"]
    assert order["test_kb.py"] > order["test_path_view.py"]


def test_path_runs_before_stateful_2fa_flow():
    conftest = importlib.import_module("tests.e2e.conftest")
    order = conftest.E2E_FILE_ORDER
    assert order["test_path_view.py"] < order["test_2fa.py"]
