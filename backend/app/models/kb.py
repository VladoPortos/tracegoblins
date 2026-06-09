import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KbSignature(Base):
    __tablename__ = "kb_signatures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # NULL team_id = the admin-promotable global tier.
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), default=None
    )
    signature_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # "is this actually a problem" / "where it usually lives" generalization prose.
    is_problem: Mapped[str | None] = mapped_column(Text, default=None)
    where_it_lives: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(
        String(12), server_default="needs-fix", default="needs-fix"
    )  # {needs-fix, known-issue, resolved, note}
    representative_text: Mapped[str] = mapped_column(Text, nullable=False)  # the pg_trgm target
    match_patterns: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )  # optional {regex:[…], substrings:[…]}
    links: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )  # list of {label,url}, scheme-allowlisted
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # NULL-distinct partial-unique pair (copied from 0004 controller_teams): one entry
        # per (team, key) for team rows, exactly one global row per key (team_id NULL).
        Index("uq_kb_signatures_team_key", "team_id", "signature_key",
              unique=True, postgresql_where=text("team_id IS NOT NULL")),
        Index("uq_kb_signatures_global_key", "signature_key",
              unique=True, postgresql_where=text("team_id IS NULL")),
        Index("ix_kb_signatures_team", "team_id"),
        Index("ix_kb_signatures_status", "status"),
        Index("ix_kb_signatures_rep_trgm", "representative_text",
              postgresql_using="gin", postgresql_ops={"representative_text": "gin_trgm_ops"}),
    )


class KbOccurrence(Base):
    __tablename__ = "kb_occurrences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    signature_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kb_signatures.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    task_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    host: Mapped[str | None] = mapped_column(Text, default=None)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("signature_id", "run_id", "task_seq",
                         name="uq_kb_occurrences_sig_run_seq"),
        Index("ix_kb_occurrences_signature", "signature_id"),
        Index("ix_kb_occurrences_run", "run_id"),
    )
