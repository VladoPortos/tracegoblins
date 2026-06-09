from __future__ import annotations

import json
import re

from app.logparser.models import HostRecap, ParsedMeta, ParsedRun, ParsedTask, Play

RE_PLAY = re.compile(r"^PLAY \[(?P<name>.*)\] \*+\s*$")
RE_PLAY_RECAP = re.compile(r"^PLAY RECAP \*+\s*$")
RE_TASK = re.compile(r"^(?:TASK|RUNNING HANDLER) \[(?P<title>.*)\] \*+\s*$")
RE_INCLUDED = re.compile(r"^included: (?P<inc>\S+) for (?P<host>.+?)\s*$")
RE_STATUS = re.compile(
    r"^(?P<verb>ok|changed|skipping|failed|fatal|ignoring|unreachable): "
    r"\[(?P<host>[^\]]+)\](?P<rest>.*)$")
RE_ITEM = re.compile(r"=> \(item=")
RE_JSONOPEN = re.compile(r"=> \{\s*$")
RE_RECAP_LINE = re.compile(r"^(?P<host>\S+)\s*:\s*(?P<rest>.*\bok=\d+.*)$")
RE_WARN = re.compile(r"^\[(?:DEPRECATION )?WARNING\]")
RE_FATALJSON = re.compile(r"=> (\{.*\})\s*$")
RE_META = {
    "template": re.compile(r'Job Template Name:\s*(.+?)\s*"'),
    "job_id": re.compile(r'Job Id:\s*(.+?)\s*"'),
    "user": re.compile(r'AWX User:\s*(.+?)\s*"'),
    "log_time": re.compile(r'Current Log Time:\s*(.+?)\s*"'),
}
OUTPUT_CAP = 1200
STATUS_NORM = {"skipping": "skipped"}
META_TASK_NAME = "Display AWX job info"


def _extract_error(line: str) -> str | None:
    m = RE_FATALJSON.search(line)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return m.group(1)[:OUTPUT_CAP]
    msg = data.get("msg")
    return msg if isinstance(msg, str) else m.group(1)[:OUTPUT_CAP]


def parse_stdout(text: str) -> ParsedRun:
    plays: list[Play] = []
    recap: list[HostRecap] = []
    meta: dict[str, str] = {}
    cur_play: Play | None = None
    cur_task: ParsedTask | None = None
    warnings = 0
    in_recap = False
    in_meta_task = False
    capturing = False
    out_lines: list[str] = []
    item_host_seen: set[str] = set()

    def close_task() -> None:
        nonlocal cur_task, capturing, out_lines, item_host_seen
        if cur_task is not None:
            cur_task.output = "\n".join(out_lines)[:OUTPUT_CAP]
        cur_task, capturing, out_lines, item_host_seen = None, False, [], set()

    for idx, line in enumerate(text.split("\n")):
        lineno = idx + 1

        if RE_WARN.match(line):
            warnings += 1
            continue

        m = RE_PLAY.match(line)
        if m:
            close_task()
            in_meta_task = in_recap = False
            cur_play = Play(name=m.group("name"), tasks=[])
            plays.append(cur_play)
            continue
        if RE_PLAY_RECAP.match(line):
            close_task()
            in_meta_task = False
            in_recap = True
            cur_play = None
            continue

        m = RE_TASK.match(line)
        if m:
            close_task()
            full = m.group("title")
            role, name = full.split(" : ", 1) if " : " in full else (None, full)
            cur_task = ParsedTask(name=name, role=role, full=full, line=lineno)
            if cur_play is None:
                cur_play = Play(name="", tasks=[])
                plays.append(cur_play)
            cur_play.tasks.append(cur_task)
            in_meta_task = name == META_TASK_NAME
            continue

        if in_recap:
            m = RE_RECAP_LINE.match(line)
            if m:
                t = {"ok": 0, "changed": 0, "unreachable": 0, "failed": 0,
                     "skipped": 0, "rescued": 0, "ignored": 0}
                for k, v in re.findall(r"(\w+)=(\d+)", m.group("rest")):
                    if k in t:
                        t[k] = int(v)
                recap.append(HostRecap(host=m.group("host"), **t))
            continue

        m = RE_INCLUDED.match(line)
        if m and cur_task is not None:
            inc, host = m.group("inc"), m.group("host")
            if inc.startswith("/"):
                cur_task.statuses[host] = "included"
                cur_task.included_path = inc
            capturing = False
            continue

        m = RE_STATUS.match(line)
        if m and cur_task is not None:
            verb, host, rest = m.group("verb"), m.group("host"), m.group("rest")
            is_item = bool(RE_ITEM.search(rest))
            if verb == "fatal":
                st = "unreachable" if "UNREACHABLE!" in line else "failed"
                if cur_task.error is None:
                    cur_task.error = _extract_error(line)
            elif verb in ("unreachable", "failed"):
                st = verb
            elif verb == "ignoring":
                st = "failed"
            else:
                st = STATUS_NORM.get(verb, verb)
            if is_item:
                cur_task.items += 1
                if host not in item_host_seen:  # first item line wins
                    cur_task.statuses[host] = st
                    item_host_seen.add(host)
            else:
                cur_task.statuses[host] = st  # bare summary always overrides
            if RE_JSONOPEN.search(line) and verb in ("ok", "changed"):
                capturing, out_lines = True, []
            elif capturing:
                capturing = False
            continue

        if in_meta_task:
            for key, rx in RE_META.items():
                if key not in meta:
                    mm = rx.search(line)
                    if mm:
                        meta[key] = mm.group(1)

        if capturing and cur_task is not None:
            if line.strip() == "":
                capturing = False
            else:
                out_lines.append(line)
            continue

    close_task()
    task_count = sum(len(p.tasks) for p in plays)
    return ParsedRun(
        meta=ParsedMeta(template=meta.get("template"), job_id=meta.get("job_id"),
                        user=meta.get("user"), log_time=meta.get("log_time")),
        recap=recap, warnings=warnings, task_count=task_count, plays=plays)
