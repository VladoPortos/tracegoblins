from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
PAGE_SIZE = 200
FINISHED_FILTER = "&not__status=running&not__status=pending&not__status=waiting&not__status=new"
# Safety backstop: never accumulate more than this many job_events for a single job. A normal
# job has hundreds-to-low-thousands of events; a pathological/hostile job could otherwise OOM
# the worker. On overflow we stop paging and log (the parse is best-effort from what we have).
MAX_JOB_EVENTS = 200_000

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int | None]:
    """(scheme, lowercased host, effective port) for same-origin comparison."""
    p = urlsplit(url)
    port = p.port or _DEFAULT_PORTS.get(p.scheme)
    return (p.scheme, (p.hostname or "").lower(), port)


def _safe_next(base: str, next_url: str | None) -> str | None:
    """Validate a DRF ``next`` pagination URL before following it.

    AWX returns ``next`` as an absolute URL, and the shared httpx client carries the
    ``Authorization: Bearer`` header on EVERY request it makes — including to a different
    host. So a malicious or misconfigured AWX that points ``next`` at another origin would
    exfiltrate the controller token. Only follow ``next`` when it is same-origin as
    ``base_url`` (a relative ``next`` is inherently same-origin once httpx resolves it).
    Anything off-origin raises AwxError rather than leaking the token.
    """
    if not next_url:
        return None
    parts = urlsplit(next_url)
    if not parts.scheme and not parts.netloc:
        return next_url  # relative -> httpx resolves against base_url (same origin)
    if _origin(next_url) != _origin(base):
        raise AwxError(
            f"AWX pagination 'next' pointed off-origin "
            f"({parts.scheme}://{parts.netloc}); refusing to send the token there"
        )
    return next_url


class AwxError(Exception):
    """Any AWX auth/connection/HTTP/parse failure. `status` is the HTTP code if there was one."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class JobSummary:
    id: int                         # job.id (the cursor key)
    name: str                       # job.name == template name (summary_fields.job_template.name)
    status: str                     # successful|failed|error|canceled
    started: str | None             # ISO -> Run.launched_at
    finished: str | None            # ISO -> Run.log_time
    elapsed: float | None           # seconds (job.elapsed)
    launch_type: str | None         # manual|scheduled|sync|workflow
    organization_id: int | None     # summary_fields.organization.id (fallback top-level job.organization)
    organization_name: str | None   # summary_fields.organization.name (e.g. "DXC")
    created_by_username: str | None # summary_fields.created_by.username (e.g. "cloudauto")
    workflow_name: str | None       # summary_fields.workflow_job.name (None unless launch_type=workflow)
    url: str                        # job.url (relative) -> Run.awx_job_url (joined to base_url)


def _to_summary(job: dict) -> JobSummary:
    """Map a raw AWX job dict (with summary_fields) to a JobSummary."""
    sf = job.get("summary_fields") or {}
    jt = sf.get("job_template") or {}
    org = sf.get("organization") or {}
    created_by = sf.get("created_by") or {}
    workflow_job = sf.get("workflow_job") or {}

    org_id = org.get("id") if org else job.get("organization")
    org_name = org.get("name") if org else None

    return JobSummary(
        id=job["id"],
        name=jt.get("name") or job.get("name") or "",
        status=job["status"],
        started=job.get("started"),
        finished=job.get("finished"),
        elapsed=job.get("elapsed"),
        launch_type=job.get("launch_type"),
        organization_id=org_id,
        organization_name=org_name,
        created_by_username=created_by.get("username"),
        workflow_name=workflow_job.get("name") if workflow_job else None,
        url=job["url"],
    )


class AwxClient:
    """One client bound to a single controller's creds. Use as an async context manager."""

    def __init__(
        self,
        base_url: str,
        token: str,
        verify_ssl: bool,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ):
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            verify=verify_ssl,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        self.last_list_count: int | None = None

    async def __aenter__(self) -> "AwxClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _get_json(self, url: str) -> dict:
        """GET url, raise AwxError on HTTP/connect/timeout/parse errors."""
        try:
            resp = await self._client.get(url)
            if resp.status_code == 401:
                raise AwxError("AWX authentication failed", status=401)
            resp.raise_for_status()
        except AwxError:
            raise
        except httpx.HTTPStatusError as exc:
            raise AwxError(str(exc), status=exc.response.status_code) from exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise AwxError(f"Cannot reach AWX: {exc}") from exc

        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise AwxError("AWX returned non-JSON response") from exc

    async def ping(self) -> dict:
        """GET /api/v2/ping/ (version) + GET /api/v2/me/ (identity).
        Returns {"version": str, "identity": str|None}. Raises AwxError on auth/conn/HTTP."""
        ping_data = await self._get_json("/api/v2/ping/")
        version = ping_data.get("version")

        me_data = await self._get_json("/api/v2/me/")
        results = me_data.get("results") or []
        identity = results[0].get("username") if results else None

        return {"version": version, "identity": identity}

    async def list_jobs(self, since_id: int) -> AsyncIterator[JobSummary]:
        """Async-iterate finished type='job' jobs with id > since_id, oldest->newest.
        Records the DRF `count` of the first page in `self.last_list_count` so a caller
        (sync_controller) can show an N/M progress total without an extra request."""
        url: str | None = (
            f"/api/v2/jobs/?id__gt={since_id}&order_by=id&page_size={PAGE_SIZE}{FINISHED_FILTER}"
        )
        self.last_list_count = None
        first = True
        while url is not None:
            data = await self._get_json(url)
            if first:
                self.last_list_count = data.get("count")
                first = False
            for job in data.get("results") or []:
                yield _to_summary(job)
            url = _safe_next(self._base, data.get("next"))

    async def get_job_events(self, job_id: int) -> list[dict]:
        """Paginate GET /api/v2/jobs/{job_id}/job_events/?page_size=200&order_by=counter,
        follow `next`, return the raw event dicts (ordered by counter) for parse_job_events()."""
        url: str | None = f"/api/v2/jobs/{job_id}/job_events/?page_size={PAGE_SIZE}&order_by=counter"
        events: list[dict] = []
        while url is not None:
            data = await self._get_json(url)
            events.extend(data.get("results") or [])
            if len(events) >= MAX_JOB_EVENTS:
                logger.warning(
                    "job %s exceeded MAX_JOB_EVENTS (%d); truncating event stream",
                    job_id, MAX_JOB_EVENTS,
                )
                del events[MAX_JOB_EVENTS:]
                break
            url = _safe_next(self._base, data.get("next"))
        return events
