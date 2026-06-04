from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Notification, Run, RunShare, TeamMember


async def create_share_notifications(
    db: AsyncSession, *, run: Run, share: RunShare, actor_id: uuid.UUID
) -> None:
    """Fan a `share` notification to each newly-granted recipient.

    Direct (user) share -> one notification for that user.
    Team share -> one notification per current team member.
    The sharer (`actor_id`) is always excluded (no self-notification).
    Caller owns the transaction (does NOT commit).
    """
    if share.shared_with_user_id is not None:
        recipient_ids: set[uuid.UUID] = {share.shared_with_user_id}
    else:
        recipient_ids = set((await db.execute(
            select(TeamMember.user_id).where(
                TeamMember.team_id == share.shared_with_team_id
            )
        )).scalars().all())
    recipient_ids.discard(actor_id)
    for uid in recipient_ids:
        db.add(Notification(
            user_id=uid, type="share", run_id=run.id,
            comment_id=None, actor_user_id=actor_id,
        ))


async def create_mention_notifications(
    db: AsyncSession, *, comment: Comment, mention_ids: Iterable[uuid.UUID],
    actor_id: uuid.UUID,
) -> None:
    """Create a `mention` notification per id in `mention_ids` (already
    validated run-visible by the caller), excluding the comment author.
    Caller owns the transaction (does NOT commit)."""
    seen: set[uuid.UUID] = set()
    for uid in mention_ids:
        if uid == actor_id or uid in seen:
            continue
        seen.add(uid)
        db.add(Notification(
            user_id=uid, type="mention", run_id=comment.run_id,
            comment_id=comment.id, actor_user_id=actor_id,
        ))
