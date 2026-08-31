from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import KbOccurrence, KbSignature, Run, Team

pytestmark = pytest.mark.asyncio

# A minimal AWX-style stdout log with one SSH-connect failure the parser stores in tasks.error.
# The parser already JSON-encodes the Ansible res blob into Task.error; we instead seed a KB
# signature + assert that uploading a log whose failed task carries the SSH error auto-matches.
_LOG = """\
PLAY [all] *********************************************************************

TASK [Gather facts] ***********************************************************
fatal: [host01]: UNREACHABLE! => {"changed": false, "msg": "Failed to connect to the host via ssh: Warning: Permanently added '100.66.0.108' (ED25519) to the list of known hosts.\\nLoad key \\"/tmp/ansible._7oamnkx_ssh_cert\\": invalid format", "unreachable": true}

PLAY RECAP ********************************************************************
host01                     : ok=0    changed=0    unreachable=1    failed=0
"""


async def test_upload_auto_matches_existing_kb_signature(authed_client, db):
    # The authed_client's user is 'member@example.com' in the default General team.
    team = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    sig = KbSignature(
        team_id=team.id, signature_key="ssh_connection_failed", title="SSH connect fails",
        category="connectivity", status="known-issue",
        representative_text="failed to connect to the host via ssh",
    )
    db.add(sig)
    await db.flush()

    resp = await authed_client.post("/api/runs", json={"text": _LOG})
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    # An occurrence was precomputed at ingest (post-commit, best-effort).
    n = await db.scalar(
        select(func.count()).select_from(KbOccurrence)
        .join(Run, Run.id == KbOccurrence.run_id)
        .where(Run.id == run_id, KbOccurrence.signature_id == sig.id)
    )
    assert n == 1
