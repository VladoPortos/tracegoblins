"""Reject credential material in captured test fixtures.

The fixture corpus intentionally contains realistic AWX output, so generic
entropy checks are too noisy. This scanner targets credential-bearing keys and
well-known token/private-key formats while allowing the repository's explicit
redaction marker.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path


REDACTED_VALUES = {
    "",
    "***",
    "[REDACTED]",
    "[REDACTED_TEST_ID]",
    "[REDACTED_TEST_VALUE]",
}
FIXTURE_SUFFIXES = {".json", ".log", ".txt", ".yaml", ".yml"}
SENSITIVE_KEY = re.compile(
    r"password|passwd|token|secret|private[_-]?key|api[_-]?key|"
    r"vault_value|credential|activationid|customerid",
    re.IGNORECASE,
)
EMBEDDED_SECRET = re.compile(
    r'''(?ix)
    ["'][^"']*(?:password|passwd|token|secret|private[_-]?key|api[_-]?key|
    vault_value|credential|activationid|customerid)[^"']*["']
    \s*:\s*["']
    (?!\[REDACTED(?:_TEST_(?:ID|VALUE))?\])
    [^"'\r\n]+["']
    ''',
)
LABELED_SECRET = re.compile(
    r"(?i)\b(?:password|passwd|api[_-]?key|token|secret)\s*[:=]\s*"
    r"(?!\[REDACTED(?:_TEST_(?:ID|VALUE))?\])[^\s,;\"']{6,}",
)
KNOWN_TOKEN = re.compile(
    r"(?:dt0c01\.[A-Za-z0-9.]{12,}|AKIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AIza[0-9A-Za-z_-]{30,})"
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def _is_unredacted_scalar(value: object) -> bool:
    return isinstance(value, str) and value.strip() not in REDACTED_VALUES


def _scan_text(value: str, location: str) -> Iterator[str]:
    for label, pattern in (
        ("embedded credential", EMBEDDED_SECRET),
        ("labeled credential", LABELED_SECRET),
        ("known token format", KNOWN_TOKEN),
        ("private key", PRIVATE_KEY),
    ):
        if pattern.search(value):
            yield f"{location}: {label}"


def _scan_json(value: object, location: str) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}" if location else key
            if SENSITIVE_KEY.search(key) and _is_unredacted_scalar(child):
                yield f"{child_location}: unredacted sensitive value"
            yield from _scan_json(child, child_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _scan_json(child, f"{location}[{index}]")
    elif isinstance(value, str):
        yield from _scan_text(value, location)


def _fixture_paths(root: Path) -> Iterator[Path]:
    if root.is_file():
        if root.suffix.lower() in FIXTURE_SUFFIXES:
            yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in FIXTURE_SUFFIXES:
            yield path


def find_fixture_secrets(root: Path) -> list[str]:
    findings: list[str] = []
    for path in _fixture_paths(root):
        display_path = path.relative_to(root) if root.is_dir() else Path(path.name)
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                findings.append(f"{display_path}:{exc.lineno}: invalid JSON")
                continue
            findings.extend(
                f"{display_path}:{finding}"
                for finding in _scan_json(value, "")
            )
        else:
            findings.extend(
                f"{display_path}:{finding}"
                for finding in _scan_text(text, "contents")
            )
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_fixture_secrets.py PATH", file=sys.stderr)
        return 2

    root = Path(argv[1]).resolve()
    if not root.exists():
        print(f"fixture path does not exist: {root}", file=sys.stderr)
        return 2

    findings = find_fixture_secrets(root)
    if findings:
        print("Potential credentials found in test fixtures:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Fixture credential scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
