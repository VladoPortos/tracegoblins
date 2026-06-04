from __future__ import annotations

from dataclasses import dataclass, field

STATUS_ORDER = ["unreachable", "failed", "changed", "ok", "included", "skipped"]


@dataclass
class ParsedMeta:
    template: str | None = None
    job_id: str | None = None
    user: str | None = None
    log_time: str | None = None


@dataclass
class HostRecap:
    host: str
    ok: int = 0
    changed: int = 0
    unreachable: int = 0
    failed: int = 0
    skipped: int = 0
    rescued: int = 0
    ignored: int = 0


@dataclass
class ParsedTask:
    name: str
    role: str | None = None
    full: str = ""
    line: int | None = None
    statuses: dict[str, str] = field(default_factory=dict)  # host -> status
    items: int = 0
    output: str = ""
    error: str | None = None
    included_path: str | None = None
    duration_s: float | None = None  # job_events only; None for stdout

    def dominant(self) -> str:
        vals = set(self.statuses.values())
        for s in STATUS_ORDER:
            if s in vals:
                return s
        return "skipped"


@dataclass
class Play:
    name: str
    tasks: list[ParsedTask] = field(default_factory=list)


@dataclass
class ParsedRun:
    meta: ParsedMeta = field(default_factory=ParsedMeta)
    recap: list[HostRecap] = field(default_factory=list)
    warnings: int = 0
    task_count: int = 0
    plays: list[Play] = field(default_factory=list)
