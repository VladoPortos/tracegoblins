"""Single source of truth for a run's *effective* timestamp ordering.

Effective time = first non-null of (AWX launch, log/finish import time, row creation).
Both the SQL expression (for WHERE / ORDER BY) and the Python form (for an already
loaded Run) live here so the precedence rule is defined exactly once. Kept
dependency-light (models only) so both API and service modules can import it
without a layering cycle.
"""
from __future__ import annotations

from sqlalchemy import func

from app.models import Run


def run_when_expr():
    """SQL ``coalesce(launched_at, log_time, created_at)`` for WHERE / ORDER BY."""
    return func.coalesce(Run.launched_at, Run.log_time, Run.created_at)


def run_effective_when(run: Run):
    """Python equivalent of :func:`run_when_expr` for an already-loaded Run."""
    return run.launched_at or run.log_time or run.created_at
