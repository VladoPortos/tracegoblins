import uuid
from datetime import UTC, datetime

from app.models import Run
from app.services.runs_query import run_to_card


def test_run_to_card_exposes_awx_fields():
    run = Run(
        id=uuid.uuid4(),
        source="awx",
        status="failed",
        template_name="Day2Actions",
        host_count=1,
        task_count=3,
        warnings_count=0,
        recap=[],
        created_at=datetime.now(UTC),
        controller_id=uuid.uuid4(),
        awx_organization_id=2,
        awx_organization_name="DXC",
        awx_launch_type="manual",
        awx_user="cloudauto",
    )
    card = run_to_card(run, controller_name="AWX dev")
    assert card.awx_organization_name == "DXC"
    assert card.awx_launch_type == "manual"
    assert card.controller_id == str(run.controller_id)
    assert card.controller_name == "AWX dev"


def test_run_to_card_exposes_scm_revision():
    rev = "abc123def456"
    run = Run(
        id=uuid.uuid4(),
        source="awx",
        status="successful",
        template_name="Deploy",
        host_count=1,
        task_count=2,
        warnings_count=0,
        recap=[],
        created_at=datetime.now(UTC),
        scm_revision=rev,
    )
    card = run_to_card(run)
    assert card.scm_revision == rev


def test_run_to_card_scm_revision_none_when_absent():
    run = Run(
        id=uuid.uuid4(),
        source="upload",
        status="successful",
        template_name=None,
        host_count=0,
        task_count=0,
        warnings_count=0,
        recap=[],
        created_at=datetime.now(UTC),
    )
    card = run_to_card(run)
    assert card.scm_revision is None
