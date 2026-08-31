from __future__ import annotations

from app.api.kb_schemas import (
    KB_STATUS_VALUES,
    KbSuggestionOut,
    PromoteIn,
    SignatureCreate,
    SignatureOut,
    SignatureUpdate,
    SuggestOut,
)
from app.api.collab_schemas import AnnotationLink


def test_status_values_are_the_four_kb_states():
    assert KB_STATUS_VALUES == frozenset({"needs-fix", "known-issue", "resolved", "note"})


def test_signature_create_defaults():
    c = SignatureCreate(
        signature_key="ssh_connection_failed",
        representative_text="failed to connect to the host via ssh",
        title="SSH unreachable",
    )
    assert c.status == "needs-fix"
    assert c.team_id is None
    assert c.links == []
    assert c.match_patterns is None


def test_signature_create_accepts_links_and_team():
    c = SignatureCreate(
        signature_key="k",
        representative_text="t",
        title="T",
        team_id="11111111-1111-1111-1111-111111111111",
        status="known-issue",
        links=[AnnotationLink(label="Runbook", url="https://wiki/x")],
    )
    assert c.team_id == "11111111-1111-1111-1111-111111111111"
    assert c.status == "known-issue"
    assert c.links[0].url == "https://wiki/x"


def test_signature_update_all_optional():
    u = SignatureUpdate()
    assert u.title is None and u.status is None and u.links is None


def test_promote_in_requires_run_and_seq():
    p = PromoteIn(run_id="r", task_seq=3, title="Fix it")
    assert p.run_id == "r" and p.task_seq == 3 and p.status == "needs-fix"


def test_suggest_out_shape():
    s = SuggestOut(signature_key="k", representative_text="t", category="connectivity")
    assert s.category == "connectivity"


def test_signature_out_round_trips_occurrence_count():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    out = SignatureOut(
        id="s1", team_id=None, signature_key="k", title="T", status="needs-fix",
        category=None, description=None, is_problem=None, where_it_lives=None,
        representative_text="t", links=[],
        occurrence_count=7, created_at=now, updated_at=now,
    )
    assert out.occurrence_count == 7


def test_kb_suggestion_out_nests_signature():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    sig = SignatureOut(
        id="s1", team_id=None, signature_key="k", title="T", status="needs-fix",
        category=None, description=None, is_problem=None, where_it_lives=None,
        representative_text="t", links=[],
        occurrence_count=2, created_at=now, updated_at=now,
    )
    card = KbSuggestionOut(signature=sig, exact=True, score=1.0)
    assert card.exact is True and card.signature.occurrence_count == 2
