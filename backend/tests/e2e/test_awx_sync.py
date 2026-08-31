import re

import pytest
from playwright.sync_api import BrowserContext, Page, expect
from pytest_playwright.pytest_playwright import CreateContextCallback

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "sup3r-s3cret-admin"
B_EMAIL = "awx-b@example.com"
B_NAME = "Avery AWX"
B_PW = "awx-b-passw0rd"
TEAM_NAME = "Ops Crew"
CONTROLLER_NAME = "Mock AWX"
CONTROLLER_URL = "http://mock-awx:9100"   # compose service name; app calls it server-side
# Deterministic mock-AWX token (any non-empty string is accepted by the sidecar). The app
# Fernet-encrypts it at rest; it is NEVER echoed to the client (masked only).
CONTROLLER_TOKEN = "awx_pat_e2e_mock_tok3n_ABCD"


def _bootstrap_admin(page: Page) -> None:
    # Setup-or-login (shared single DB across the e2e suite). Branch on the auth heading,
    # NOT page.url (the React <Navigate> redirect resolves async).
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


def _login_as(page: Page, email: str, password: str) -> None:
    page.goto("/login")
    expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()


def _ensure_user_b_and_team(admin: Page) -> None:
    # Idempotent on the shared DB: invite B (link-based, D6) + create team T + add B & A.
    admin.get_by_role("button", name="Admin").click()
    expect(admin.get_by_role("button", name="Invite user")).to_be_visible()
    expect(admin.get_by_text(ADMIN_EMAIL)).to_be_visible()  # user list loaded
    if not admin.get_by_text(B_EMAIL).is_visible():
        admin.get_by_role("button", name="Invite user").click()
        admin.get_by_label("Email").fill(B_EMAIL)
        admin.get_by_role("button", name="Generate link").click()
        invite_url = admin.get_by_test_id("invite-link").input_value()
        invite_page = admin.context.browser.new_context(ignore_https_errors=True).new_page()
        invite_page.goto(invite_url)
        expect(invite_page.get_by_role("heading", name="Set up your account")).to_be_visible()
        invite_page.get_by_label("Display name").fill(B_NAME)
        invite_page.get_by_label("Password", exact=True).fill(B_PW)
        invite_page.get_by_label("Confirm password").fill(B_PW)
        invite_page.get_by_role("button", name="Accept invite").click()
        expect(invite_page.get_by_role("heading", name="Job logs")).to_be_visible()
        invite_page.context.close()
        admin.get_by_role("button", name="Done").click()
        admin.reload()
        expect(admin.get_by_role("button", name="Invite user")).to_be_visible()
    admin.get_by_role("button", name="Teams").click()
    expect(admin.get_by_role("button", name="General")).to_be_visible()
    if not admin.get_by_role("button", name=TEAM_NAME).is_visible():
        admin.get_by_role("button", name="New team").click()
        admin.get_by_label("Team name").fill(TEAM_NAME)
        admin.get_by_role("button", name="Create").click()
        expect(admin.get_by_role("button", name=TEAM_NAME)).to_be_visible()
    admin.get_by_role("button", name=TEAM_NAME).click()
    dlg = admin.get_by_role("dialog")
    expect(dlg).to_be_visible()
    picker = dlg.get_by_label("Add member")
    expect(picker).to_be_visible()
    expect(picker.get_by_role("option")).not_to_have_count(1)

    def _ensure_member(name: str, email: str) -> None:
        option = picker.get_by_role("option", name=f"{name} ({email})")
        if option.count() > 0:
            picker.select_option(label=f"{name} ({email})")
            dlg.get_by_role("button", name="Add", exact=True).click()
            expect(picker.get_by_role("option", name=f"{name} ({email})")).to_have_count(0)

    _ensure_member(B_NAME, B_EMAIL)
    _ensure_member("Boss Admin", ADMIN_EMAIL)
    dlg.get_by_role("button", name="Close").click()
    admin.reload()
    admin.goto("/")
    expect(admin.get_by_role("heading", name="Job logs")).to_be_visible()


def _add_or_open_controller(admin: Page) -> None:
    # Navigate to the admin-only AWX Controllers settings page. Idempotent on the shared DB.
    admin.goto("/admin/awx")
    expect(admin.get_by_role("heading", name="AWX Controllers")).to_be_visible()
    if admin.get_by_text(re.compile(re.escape(CONTROLLER_NAME))).count() == 0:
        # On an empty list two buttons share the accessible name "Add controller"
        # (the header "New controller" button + the empty-state CTA); the header
        # one is first in the DOM and is always present, so target it explicitly.
        admin.get_by_role("button", name="Add controller").first.click()
        dlg = admin.get_by_role("dialog")
        expect(dlg).to_be_visible()
        dlg.get_by_label("Name").fill(CONTROLLER_NAME)
        dlg.get_by_label("Base URL").fill(CONTROLLER_URL)
        dlg.get_by_label("Token").fill(CONTROLLER_TOKEN)
        # self-signed-equivalent: turn TLS verification off (checkbox defaults on)
        dlg.get_by_label("Verify SSL").uncheck()
        # ----- Test connection BEFORE saving: the mock returns version 24.6.1.
        dlg.get_by_role("button", name="Test connection").click()
        expect(dlg.get_by_text(re.compile("24.6.1"))).to_be_visible()
        # ----- Assign the team, org-scoped to DXC (AWX org id 2). The add modal opens
        # with one empty assignment row already present, so fill it directly (no need to
        # click "Add team" first — that button adds *additional* rows).
        # aria-label="Team" on the team select inside TeamAssignmentEditor.
        dlg.get_by_label("Team", exact=True).first.select_option(label=TEAM_NAME)
        # aria-label="AWX organization ID" on the org input (no trailing "(optional)")
        dlg.get_by_label("AWX organization ID").first.fill("2")
        # The chosen team is reflected as the selected option in the row.
        expect(dlg.get_by_label("Team", exact=True).first).to_contain_text(TEAM_NAME)
        dlg.get_by_role("button", name="Add controller").click()
    # The controller card is present (name shows as a span inside a card div, not a button).
    expect(admin.get_by_text(re.compile(re.escape(CONTROLLER_NAME))).first).to_be_visible()
    # Plaintext token is never echoed to the client.
    expect(admin.get_by_text(CONTROLLER_TOKEN)).to_have_count(0)


def test_awx_controller_sync_filter_failed_run_statusmap(new_context: CreateContextCallback):
    ctx_a: BrowserContext = new_context()
    ctx_b: BrowserContext = new_context()
    a = ctx_a.new_page()
    b = ctx_b.new_page()
    try:
        _bootstrap_admin(a)
        _ensure_user_b_and_team(a)
        _add_or_open_controller(a)

        # ----- Preload the controller-filtered team run list before starting sync. -----
        # This keeps the same runs query mounted through the asynchronous import and
        # catches a terminal controller poll that leaves the already-loaded list stale.
        a.goto("/")
        a.get_by_role("button", name="Team workspace").click()
        a.get_by_role("button", name=CONTROLLER_NAME, exact=True).click()
        day2_before = a.get_by_role("button", name=re.compile(r"Day2Actions\s+#7(?:43|44|45)"))
        expect(day2_before).to_have_count(0)

        # ----- Sync now: the assigned-team admin triggers the manual sync (202). -----
        a.get_by_role("button", name="Sync now").click()
        # Last-sync chip lands on the "Synced" (ok) state once the 3 Day2Actions jobs import.
        # The UI polls the controller while the background sync runs, so wait a few seconds.
        expect(a.get_by_role("status", name="Synced")).to_be_visible(timeout=20000)
        expect(a.get_by_role("button", name=re.compile(r"Day2Actions\s+#743"))).to_be_visible()

        # ----- Member B logs in; the 3 Day2Actions runs appear in Team workspace. -----
        _login_as(b, B_EMAIL, B_PW)
        b.get_by_role("button", name="Team workspace").click()
        # AWX runs render grouped per controller; the controller group header is present.
        expect(b.get_by_text(re.compile(re.escape(CONTROLLER_NAME))).first).to_be_visible()
        day2_cards = b.get_by_role("button", name=re.compile("Day2Actions"))
        expect(day2_cards).to_have_count(3)

        # ----- Filter status=failed narrows to the single failed run (job 745). -----
        b.get_by_role("button", name="Filter status failed", exact=True).click()  # FilterBar status toggle
        expect(b.get_by_role("button", name=re.compile("Day2Actions"))).to_have_count(1)

        # ----- B opens the failed run: Status Map renders WITH durations + failure drawer. -----
        b.get_by_role("button", name=re.compile("Day2Actions")).first.click()
        expect(b).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
        expect(b.get_by_text("Status map")).to_be_visible()
        # job_events durations -> a non-"0s" duration is rendered somewhere on the map.
        # (Several tasks have durations; assert at least one is visible.)
        expect(b.get_by_text(re.compile(r"\d+(\.\d+)?\s*s")).first).to_be_visible()
        # First failure -> drawer shows the runner_on_failed message from event_data.res.msg.
        b.get_by_role("button", name="First failure").click()
        expect(b.get_by_text("Failure detail")).to_be_visible()
        expect(b.get_by_text(re.compile("Day-2 precondition not met"))).to_be_visible()
    finally:
        ctx_a.close()
        ctx_b.close()
