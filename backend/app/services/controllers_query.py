from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.controllers_schemas import ControllerOut, ControllerTeamOut
from app.core.crypto import decrypt_token, mask_token
from app.models import AwxController, ControllerTeam, Team


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


async def controller_to_out(
    db: AsyncSession, c: AwxController, *, viewer_team_ids: set[uuid.UUID] | None = None
) -> ControllerOut:
    """Serialize a controller. The token is ALWAYS masked here (decrypt -> mask); the
    plaintext is never placed on the response model, so it cannot leak to a client.

    ``viewer_team_ids`` is the redaction switch for NON-ADMIN callers:
      - None (default, admin/full view): all team assignments + the masked token tail.
      - a set (a member listing team-visible controllers): assignments are filtered to the
        viewer's OWN teams (so other teams' names/ids/org scopes don't leak), and the token
        mask is withheld entirely (token metadata is admin-only).
    """
    rows = (await db.execute(
        select(ControllerTeam.team_id, Team.name, ControllerTeam.awx_organization_id)
        .join(Team, Team.id == ControllerTeam.team_id, isouter=True)
        .where(ControllerTeam.controller_id == c.id)
        .order_by(ControllerTeam.created_at)
    )).all()
    if viewer_team_ids is not None:
        rows = [r for r in rows if r[0] in viewer_team_ids]
    assignments = [
        ControllerTeamOut(team_id=str(tid), team_name=tname, awx_organization_id=org)
        for tid, tname, org in rows
    ]
    token_masked = "" if viewer_team_ids is not None else mask_token(decrypt_token(c.auth_token_encrypted))
    return ControllerOut(
        id=str(c.id),
        name=c.name,
        base_url=c.base_url,
        verify_ssl=c.verify_ssl,
        sync_mode=c.sync_mode,
        sync_interval_minutes=c.sync_interval_minutes,
        status=c.status,
        last_sync_status=c.last_sync_status,
        last_sync_at=_iso(c.last_sync_at),
        last_sync_error=c.last_sync_error,
        last_synced_job_id=c.last_synced_job_id,
        sync_total=c.sync_total,
        sync_done=c.sync_done,
        sync_current_job=c.sync_current_job,
        token_masked=token_masked,
        team_assignments=assignments,
        created_at=c.created_at.isoformat(),
    )
