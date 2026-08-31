import pytest
from app.awx.client import _to_job_detail


def test_to_job_detail_parses_extra_vars_string():
    raw = {
        "extra_vars": '{"target_env": "prod", "db_password": "$encrypted$"}',
        "limit": "batch_3", "scm_revision": "a1b9f4c0",
        "summary_fields": {"project": {"id": 7, "name": "day2-playbooks"},
                           "job_template": {"id": 12, "name": "Day2Actions"}},
    }
    d = _to_job_detail(raw)
    assert d.extra_vars["target_env"] == "prod"
    assert d.limit == "batch_3" and d.scm_revision == "a1b9f4c0"
    assert d.project_id == 7 and d.project_name == "day2-playbooks"
    assert d.job_template_id == 12


def test_to_job_detail_tolerates_missing_and_bad_json():
    d = _to_job_detail({"extra_vars": "not json", "summary_fields": {}})
    assert d.extra_vars == {} and d.project_id is None and d.limit is None
