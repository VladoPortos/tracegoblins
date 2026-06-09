from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.models import MfaRecoveryCode, User
from app.security import totp


async def issue_recovery_codes(db: AsyncSession, user: User, *, n: int = 10) -> list[str]:
    """Replace the user's recovery-code set; return the plaintext codes (shown once).
    n=0 simply clears the set."""
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = totp.generate_recovery_codes(n)
    for c in codes:
        db.add(MfaRecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(c)))
    await db.flush()
    return codes


async def consume_recovery_code(db: AsyncSession, user: User, code: str) -> bool:
    """Mark a matching unused code used. True on success; False if no match / already used.

    Burns the code with a single atomic ``UPDATE ... WHERE used_at IS NULL`` so two concurrent
    verifies racing the same code can't both succeed: the predicate is re-evaluated under the
    row lock the UPDATE takes, so the loser sees used_at already set and matches zero rows.
    """
    h = totp.hash_recovery_code(code)
    result = await db.execute(
        update(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == h,
            MfaRecoveryCode.used_at.is_(None),
        )
        .values(used_at=utcnow())
    )
    await db.flush()
    return (result.rowcount or 0) > 0
