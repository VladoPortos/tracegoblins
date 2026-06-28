from __future__ import annotations

import json
from datetime import datetime

from app.core import statuses
from app.core.clock import parse_iso
from app.logparser.models import HostRecap, ParsedRun, ParsedTask, Play

_TERMINAL = {
    "runner_on_ok": "ok",  # -> 'changed' if res.changed
    "runner_on_failed": "failed",
    "runner_on_unreachable": "unreachable",
    "runner_on_skipped": "skipped",
}
_ITEM = {"runner_item_on_ok": "ok", "runner_item_on_failed": "failed", "runner_item_on_skipped": "skipped"}

# Cap a single task's serialized result blob (output/error). A hostile or pathological AWX
# result dict could otherwise store unbounded JSON per task; 64k is far above any real message.
_MAX_BLOB_CHARS = 64_000


def _norm(s: str) -> str:
    s = s or ""
    return s[3:] if s.startswith("v2_") else s


def _host(ev: dict) -> str | None:
    # Real AWX: top-level "host" is an integer DB record ID, not a hostname.
    # The actual hostname lives in event_data.host / event_data.remote_addr.
    # We only fall back to top-level "host" when it is already a string (synthetic
    # fixtures and future-proofing if AWX ever changes the field type).
    ed = ev.get("event_data") or {}
    h = ed.get("host") or ed.get("remote_addr")
    if h:
        return h
    top = ev.get("host")
    return top if isinstance(top, str) else None


def _ts(ev: dict) -> datetime | None:
    # the shared parser also normalizes tz (the old local copy didn't) — XMOD4
    return parse_iso(ev.get("created"))


def _res_blob(res: dict | None) -> str:
    if not res:
        return ""
    s = json.dumps(res, ensure_ascii=False)
    if len(s) > _MAX_BLOB_CHARS:
        s = s[:_MAX_BLOB_CHARS] + "…[truncated]"
    return s


def parse_job_events(events: list[dict]) -> ParsedRun:
    run = ParsedRun()
    plays: list[Play] = []
    cur_play: Play | None = None
    cur_task: ParsedTask | None = None
    task_start: datetime | None = None
    task_last: datetime | None = None
    item_best: dict[str, str] = {}

    def _close_task() -> None:
        nonlocal cur_task, task_start, task_last, item_best
        if cur_task is not None:
            for h, st in item_best.items():
                cur_task.statuses.setdefault(h, st)
            if task_start and task_last and task_last >= task_start:
                cur_task.duration_s = (task_last - task_start).total_seconds()
        task_start = task_last = None
        item_best = {}

    def _open_task(ed: dict, ev: dict, included: bool) -> None:
        nonlocal cur_task, cur_play, task_start
        _close_task()
        if cur_play is None:
            cur_play = Play(name=ed.get("play") or "")
            plays.append(cur_play)
        name = ed.get("task") or ed.get("name") or ""
        role = ed.get("role") or None
        full = f"{role} : {name}" if role else name
        cur_task = ParsedTask(name=name, role=role, full=full, line=None)
        if included:
            cur_task.statuses[ed.get("host") or "localhost"] = "included"
        cur_play.tasks.append(cur_task)
        task_start = _ts(ev)

    for ev in events:
        et = _norm(ev.get("event", ""))
        ed = ev.get("event_data") or {}
        if et in ("warning", "system_warning"):
            run.warnings += 1
            continue
        if et == "playbook_on_play_start":
            _close_task()
            cur_play = Play(name=ed.get("play") or ed.get("name") or "")
            plays.append(cur_play)
            cur_task = None
            continue
        if et in ("playbook_on_task_start", "playbook_on_handler_task_start"):
            _open_task(ed, ev, included=False)
            continue
        if et == "playbook_on_include":
            _open_task(ed, ev, included=True)
            continue
        if et in _TERMINAL:
            if cur_task is None:
                continue
            host = _host(ev) or "localhost"
            res = ed.get("res") or {}
            status = _TERMINAL[et]
            if status == "ok" and res.get("changed"):
                status = "changed"
            cur_task.statuses[host] = status
            if status in statuses.FAIL_STATUSES:
                cur_task.error = _res_blob(res)
            elif res:
                cur_task.output = _res_blob(res)
            run.warnings += len(res.get("warnings", []) or [])
            task_last = _ts(ev) or task_last
            continue
        if et in _ITEM:
            if cur_task is None:
                continue
            res = ed.get("res") or {}
            host = _host(ev) or "localhost"
            st = _ITEM[et]
            if st == "ok" and res.get("changed"):
                st = "changed"
            cur_task.items += 1
            if statuses.rank(st) >= statuses.rank(item_best.get(host, "skipped")):
                item_best[host] = st
            if st == "failed":
                cur_task.error = cur_task.error or _res_blob(res)
            task_last = _ts(ev) or task_last
            continue
        if et == "playbook_on_stats":
            _close_task()
            run.recap = _build_recap(ed)
            continue

    _close_task()
    run.plays = plays
    run.task_count = sum(len(p.tasks) for p in plays)
    return run


def _build_recap(ed: dict) -> list[HostRecap]:
    ok = ed.get("ok", {}) or {}
    changed = ed.get("changed", {}) or {}
    dark = ed.get("dark", {}) or {}        # AWX names unreachable 'dark'
    failures = ed.get("failures", {}) or {}  # AWX names failed 'failures'
    skipped = ed.get("skipped", {}) or {}
    rescued = ed.get("rescued", {}) or {}
    ignored = ed.get("ignored", {}) or {}
    processed = ed.get("processed", {}) or {}
    hosts: list[str] = []
    seen: set[str] = set()
    for src in (processed, ok, changed, dark, failures, skipped, rescued, ignored):
        for h in src:
            if h not in seen:
                seen.add(h)
                hosts.append(h)
    return [
        HostRecap(host=h, ok=int(ok.get(h, 0)), changed=int(changed.get(h, 0)),
                  unreachable=int(dark.get(h, 0)), failed=int(failures.get(h, 0)),
                  skipped=int(skipped.get(h, 0)), rescued=int(rescued.get(h, 0)),
                  ignored=int(ignored.get(h, 0)))
        for h in hosts
    ]
