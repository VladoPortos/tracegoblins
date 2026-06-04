from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Order in which we look for a human-readable message inside an Ansible result dict.
_MESSAGE_KEYS = ("msg", "module_stderr", "stderr", "exception", "reason")


@dataclass(frozen=True)
class Signature:
    signature_key: str
    representative_text: str
    category: str | None


def _unwrap(error_text: str | None) -> str | None:
    """Step 1 — pull the human-readable message out of the (often JSON) error blob.

    Two real storage shapes (see Phase B header reconciliation #1):
      - stdout adapter: a bare Ansible ``msg`` string (json.loads fails -> use raw)
      - job_events adapter: ``json.dumps(res)`` (json.loads -> dict -> pick a key)
    Returns the stripped message, or None when there is nothing usable.
    """
    if not error_text or not error_text.strip():
        return None
    message: str | None = None
    try:
        data = json.loads(error_text)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        for key in _MESSAGE_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                message = val
                break
        if message is None:
            # dict but none of the message keys present/non-empty: fall back to the
            # serialized dict so classification still has something to bite on.
            message = json.dumps(data)
    else:
        # not JSON (or not a dict, e.g. a JSON string/number/list): use the raw text.
        message = error_text
    message = message.strip()
    return message or None


# --- Step 2: ordered classification pattern library (Contract §2). First hit wins. ---
# Each tuple: (compiled_regex, signature_key, category). Ordering is load-bearing:
#  - SSH-connect (1) before SSH-auth (2): the real ssh-connect blob also contains
#    "Permission denied (publickey" + "Load key ... invalid format".
#  - WinRM (3) before the generic Max-retries/No-route-to-host (4): ntlm/5986/wsman win.
#  - permission_denied (7) last among non-SSH so SSH/WinRM/timeout never mis-bucket.
_PF = re.IGNORECASE | re.DOTALL
PATTERN_LIBRARY: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"failed to connect to the host via ssh", _PF),
     "ssh_connection_failed", "connectivity"),
    (re.compile(
        r"load key .*invalid format|permission denied \(publickey|"
        r"host key verification failed|ssh.*authentication failed|"
        r"too many authentication failures", _PF),
     "ssh_auth_failed", "auth"),
    (re.compile(r"ntlm:|/wsman|winrm|psrp:|port=5986|port=5985", _PF),
     "winrm_connection_failed", "connectivity"),
    (re.compile(
        r"max retries exceeded|connection timed out|timed out|no route to host|"
        r"connection refused|failed to establish a new connection|"
        r"name or service not known|temporary failure in name resolution", _PF),
     "connection_timeout", "connectivity"),
    (re.compile(
        r"\bassertion\b.*fail|assert(ion)? failed|evaluated_to.{0,8}false|"
        r"\"?evaluated_to\"?\s*:\s*false", _PF),
     "assertion_failed", "precondition"),
    (re.compile(
        r"no package|could not find a version|unable to locate package|"
        r"no match for argument|nothing provides|"
        r"package .* (is )?not (found|available)", _PF),
     "package_not_found", "package"),
    (re.compile(
        r"permission denied|access ?denied|operation not permitted|not permitted|"
        r"you do not have permission|eacces", _PF),
     "permission_denied", "permission"),
]

# The assertion pattern (#5), re-used in Step 2b against the RAW error_text.
_ASSERTION_PATTERN = PATTERN_LIBRARY[4][0]


def _slug(text: str) -> str:
    """Stable, index-safe slug for the generic-fallback key: lowercase, any run of
    non-[a-z0-9] -> '-', strip leading/trailing '-', truncate to 60 chars."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60].strip("-")


def _classify(message: str, error_text: str) -> tuple[str | None, str | None]:
    """Step 2 (message-first) + Step 2b (raw-JSON assertion fallback).

    Returns (signature_key, category) when a pattern matches, else (None, None).
    """
    for pattern, key, category in PATTERN_LIBRARY:
        if pattern.search(message):
            return key, category
    # Step 2b: the assert msg ("Resource '...' not found...") has no 'assert' token,
    # but the raw res JSON has "assertion"/"evaluated_to": false. Scan it for #5 ONLY.
    if error_text and _ASSERTION_PATTERN.search(error_text):
        return "assertion_failed", "precondition"
    return None, None


# --- Step 3: host-strip substitutions (Contract §2). Applied IN THIS ORDER; the
# SSH banner first, abs-paths before the bare-port rule, whitespace-collapse last. ---
_HOST_STRIPS: list[tuple[re.Pattern[str], str]] = [
    # 1. SSH "Permanently added '<host>' ..." banner (whole line up to newline).
    (re.compile(r"warning: permanently added '[^']*'[^\n]*", re.IGNORECASE),
     "<ssh-banner>"),
    # 2. ISO-8601 timestamps.
    (re.compile(
        r"\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?",
        re.IGNORECASE),
     "<ts>"),
    # 3. UUIDs.
    (re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE),
     "<uuid>"),
    # 4. Hex addresses (0x...).
    (re.compile(r"0x[0-9a-f]+", re.IGNORECASE), "<hex>"),
    # 5. IPv4.
    (re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"), "<ip>"),
    # 6. Absolute paths (collapses /tmp/ansible.<rand>_ssh_cert -> <path>).
    (re.compile(r"/[\w./-]+"), "<path>"),
    # 7. host=.../port=... kv pairs -> <host>/<port>.
    (re.compile(r"\b(host|port)=\S+", re.IGNORECASE), r"<\1>"),
    # 8. bare ":<digits>" ports.
    (re.compile(r":\d{2,5}\b"), ":<port>"),
    # 9. whitespace collapse (applied last, then .strip().lower()).
    (re.compile(r"\s+"), " "),
]


def _host_strip(message: str) -> str:
    text = message
    for pattern, repl in _HOST_STRIPS:
        text = pattern.sub(repl, text)
    return text.strip().lower()


def extract_signature(error_text: str | None) -> Signature | None:
    message = _unwrap(error_text)
    if message is None:
        return None
    key, category = _classify(message, error_text or "")
    representative_text = _host_strip(message)
    if key is None:
        key = "generic:" + _slug(representative_text[:60])
        category = None
    return Signature(
        signature_key=key,
        representative_text=representative_text,
        category=category,
    )
