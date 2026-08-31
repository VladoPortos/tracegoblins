import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[3]
# The two SSH fixtures collapse to ONE signature: both carry "Failed to connect to the host
# via ssh" on host 100.66.0.108 but with DIFFERENT /tmp/ansible.<rand>_ssh_cert paths, so the
# abs-path strip normalizes them to the same representative_text (the §0 golden) -> "seen in
# 2 runs" after the second upload auto-matches the precomputed signature.
SSH_RUN_1 = ROOT / "backend/tests/fixtures/logs/job_11140.txt"
SSH_RUN_2 = ROOT / "backend/tests/fixtures/logs/job_11142.txt"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "sup3r-s3cret-admin"
# Template names unique to THIS file so the run cards / KB rows are greppable and don't
# collide with other e2e files on the shared DB.
RUN_TPL_1 = "KB SSH Run One"
RUN_TPL_2 = "KB SSH Run Two"
KB_TITLE = "SSH connect fails — check bastion firewall"
KB_FIX_URL = "https://runbooks.example.com/ssh-connect"


def _bootstrap_admin(page: Page) -> None:
    # Setup-or-login (shared single DB). Branch on the unique auth heading, NOT page.url
    # (the React <Navigate> redirect resolves async after the setup-status query).
    page.goto("/setup")
    setup_heading = page.get_by_role("heading", name="Create the first administrator")
    login_heading = page.get_by_role("heading", name="Sign in to your workspace")
    expect(setup_heading.or_(login_heading)).to_be_visible()
    if login_heading.is_visible():
        page.get_by_label("Email").fill(ADMIN_EMAIL)
        page.get_by_label("Password", exact=True).fill(ADMIN_PW)
        page.get_by_role("button", name="Sign in").click()
    else:
        page.get_by_label("Email").fill(ADMIN_EMAIL)
        page.get_by_label("Display name").fill("Boss Admin")
        page.get_by_label("Password", exact=True).fill(ADMIN_PW)
        page.get_by_label("Confirm password").fill(ADMIN_PW)
        page.get_by_role("button", name="Create admin").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()


def _upload(page: Page, fixture: Path, template: str) -> str:
    # Upload a log via the modal (file tab) as a PERSONAL run (default "Save to"). The run
    # lands on the Status Map (/runs/:id). Returns the run id from the URL.
    page.goto("/")
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()
    page.get_by_role("button", name="Upload log").first.click()
    page.get_by_role("button", name="Upload file").click()
    page.get_by_label("Log file").set_input_files(str(fixture))
    page.get_by_label("Template name (optional)").fill(template)
    page.get_by_role("button", name="Upload & analyze").click()
    expect(page).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    expect(page.get_by_text("Status map")).to_be_visible()
    m = re.search(r"/runs/([0-9a-f-]+)", page.url)
    assert m, f"no run id in url {page.url}"
    return m.group(1)


def test_kb_promote_match_and_promote_global(page: Page):
    _bootstrap_admin(page)

    # ---- 1) Upload the first SSH-failing run; open the failing task drawer. ----
    _upload(page, SSH_RUN_1, RUN_TPL_1)
    page.get_by_role("button", name="First failure").click()
    expect(page.get_by_text("Failure detail")).to_be_visible()

    # No KB match yet -> the drawer's Known-issue slot offers "Promote to KB" (KbSuggestion
    # renders the promote button when useTaskKbSuggestion returns null).
    promote_btn = page.get_by_role("button", name="Promote to KB")
    expect(promote_btn).to_be_visible()
    expect(page.get_by_text("Known issue")).to_have_count(0)  # no card before promote

    # ---- 2) Promote: the modal pre-fills the auto-extracted signature; fill title + fix link. ----
    promote_btn.click()
    dlg = page.get_by_role("dialog")
    expect(dlg).to_be_visible()
    # The server-extracted signature_key is shown read-only; assert the SSH key pre-filled.
    expect(dlg.get_by_text("ssh_connection_failed")).to_be_visible()
    dlg.get_by_label("Title").fill(KB_TITLE)
    # Status stays "needs-fix" (the default option of the <select className="input">).
    # Add one fix link via the add/remove link editor (label/url pair).
    dlg.get_by_role("button", name="Add link").click()
    dlg.get_by_label("Link label").fill("Runbook")
    dlg.get_by_label("Link URL").fill(KB_FIX_URL)
    # The modal's submit button is labelled "Promote to KB" (E4); match the full label.
    dlg.get_by_role("button", name="Promote to KB").click()
    expect(dlg).not_to_be_visible()

    # ---- 3) The drawer now shows the "Known issue" card: title, status badge, seen-in-1-run. ----
    expect(page.get_by_text("Known issue")).to_be_visible()
    expect(page.get_by_text(KB_TITLE)).to_be_visible()
    expect(page.get_by_text("needs-fix").first).to_be_visible()
    expect(page.get_by_text(re.compile(r"seen in 1 run\b"))).to_be_visible()
    # The fix link renders as a safe external anchor (rel/target set by KbSuggestion).
    fix_link = page.get_by_role("link", name="Runbook")
    expect(fix_link).to_have_attribute("href", KB_FIX_URL)
    expect(fix_link).to_have_attribute("rel", re.compile(r"noopener"))

    # ---- 4) Upload a SECOND, host-different SSH run; it auto-matches (precomputed on ingest). ----
    _upload(page, SSH_RUN_2, RUN_TPL_2)
    page.get_by_role("button", name="First failure").click()
    expect(page.get_by_text("Failure detail")).to_be_visible()
    # No promote button — the match is already there; the Known-issue card shows "seen in 2 runs".
    expect(page.get_by_text("Known issue")).to_be_visible()
    expect(page.get_by_text(KB_TITLE)).to_be_visible()
    expect(page.get_by_text(re.compile(r"seen in 2 runs\b"))).to_be_visible()
    expect(page.get_by_role("button", name="Promote to KB")).to_have_count(0)

    # ---- 5) KB browse page: the entry is listed/searchable; the M1 stub is gone. ----
    page.get_by_role("link", name="Knowledge base").click()
    expect(page).to_have_url(re.compile(r"/kb$"))
    expect(page.get_by_role("heading", name="Knowledge base")).to_be_visible()
    # The M1 stub copy ("built in Milestone 5") must be absent now.
    expect(page.get_by_text("built in Milestone 5")).to_have_count(0)
    # Search narrows the list to our entry by title.
    page.get_by_label("Search").fill("bastion firewall")
    row = page.get_by_role("button", name=re.compile(re.escape(KB_TITLE)))
    expect(row).to_be_visible()
    expect(page.get_by_text("ssh_connection_failed").first).to_be_visible()
    expect(page.get_by_text(re.compile(r"seen in 2 runs\b"))).to_be_visible()

    # ---- 6) Admin promotes the team signature to GLOBAL (admin-only action on the detail view). ----
    row.click()
    promote_global = page.get_by_role("button", name="Promote to global")
    expect(promote_global).to_be_visible()
    promote_global.click()
    # After promotion the entry is global; the detail view reflects it (a "Global" marker
    # replaces the team scope, and the promote-to-global control is gone).
    expect(page.get_by_text("Global").first).to_be_visible()
    expect(page.get_by_role("button", name="Promote to global")).to_have_count(0)
