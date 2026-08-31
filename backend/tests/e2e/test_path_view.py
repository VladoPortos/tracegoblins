"""E2E test for the Run Path Explorer view — driven by REAL SYNCED mock-AWX data.

Mock-AWX job 743 (successful) events now include an include container (packages.yml)
with a 3-item loop (nginx/curl/git), so the synced tree exercises both containers
and the loop stepper. This mirrors the sync bootstrap in test_awx_sync.py.

NOTE: This test requires the isolated docker-compose.e2e.yml stack (mock-awx sidecar +
app + db). When running against the heavy Docker stack, supply --base-url appropriately.
A parse-only smoke check is run in CI without Docker via:
    python -c "import ast; ast.parse(open('tests/e2e/test_path_view.py').read())"
"""
import re

import pytest
from playwright.sync_api import BrowserContext, Page, expect
from pytest_playwright.pytest_playwright import CreateContextCallback

pytestmark = pytest.mark.e2e

# Mirror constants from test_awx_sync.py — same shared e2e stack/DB.
ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "sup3r-s3cret-admin"
CONTROLLER_NAME = "Mock AWX"
CONTROLLER_URL = "http://mock-awx:9100"
CONTROLLER_TOKEN = "awx_pat_e2e_mock_tok3n_ABCD"
TEAM_NAME = "Ops Crew"


def _bootstrap_admin(page: Page) -> None:
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


def _ensure_team(admin: Page) -> None:
    """Idempotent: create Ops Crew team if absent."""
    admin.get_by_role("button", name="Admin").click()
    expect(admin.get_by_role("button", name="Invite user")).to_be_visible()
    admin.get_by_role("button", name="Teams").click()
    expect(admin.get_by_role("button", name="General")).to_be_visible()
    if not admin.get_by_role("button", name=TEAM_NAME).is_visible():
        admin.get_by_role("button", name="New team").click()
        admin.get_by_label("Team name").fill(TEAM_NAME)
        admin.get_by_role("button", name="Create").click()
        expect(admin.get_by_role("button", name=TEAM_NAME)).to_be_visible()
    # Ensure admin is a member of the team (needed for run visibility after sync)
    admin.get_by_role("button", name=TEAM_NAME).click()
    dlg = admin.get_by_role("dialog")
    expect(dlg).to_be_visible()
    picker = dlg.get_by_label("Add member")
    option = picker.get_by_role("option", name=re.compile("Boss Admin"))
    if option.count() > 0:
        picker.select_option(label=re.compile("Boss Admin"))
        dlg.get_by_role("button", name="Add", exact=True).click()
    dlg.get_by_role("button", name="Close").click()
    admin.goto("/")
    expect(admin.get_by_role("heading", name="Job logs")).to_be_visible()


def _add_or_open_controller(admin: Page) -> None:
    """Add Mock AWX controller assigned to Ops Crew, if not already present."""
    admin.goto("/admin/awx")
    expect(admin.get_by_role("heading", name="AWX Controllers")).to_be_visible()
    if admin.get_by_text(re.compile(re.escape(CONTROLLER_NAME))).count() == 0:
        admin.get_by_role("button", name="Add controller").first.click()
        dlg = admin.get_by_role("dialog")
        expect(dlg).to_be_visible()
        dlg.get_by_label("Name").fill(CONTROLLER_NAME)
        dlg.get_by_label("Base URL").fill(CONTROLLER_URL)
        dlg.get_by_label("Token").fill(CONTROLLER_TOKEN)
        dlg.get_by_label("Verify SSL").uncheck()
        dlg.get_by_role("button", name="Test connection").click()
        expect(dlg.get_by_text(re.compile("24.6.1"))).to_be_visible()
        dlg.get_by_label("Team", exact=True).first.select_option(label=TEAM_NAME)
        dlg.get_by_label("AWX organization ID").first.fill("2")
        dlg.get_by_role("button", name="Add controller").click()
    expect(admin.get_by_text(re.compile(re.escape(CONTROLLER_NAME))).first).to_be_visible()


def _sync_and_wait(admin: Page) -> None:
    """Trigger a manual sync and wait for the Synced status chip."""
    admin.goto("/admin/awx")
    expect(admin.get_by_text(re.compile(re.escape(CONTROLLER_NAME))).first).to_be_visible()
    admin.get_by_role("button", name="Sync now").first.click()
    expect(admin.get_by_role("status", name="Synced")).to_be_visible(timeout=20_000)


def _open_job_743_path(admin: Page) -> str:
    """Navigate to the team workspace, open job 743 (first successful run), then /path.
    Returns the run URL for assertions."""
    admin.goto("/")
    admin.get_by_role("button", name="Team workspace").click()
    # Select the deterministic mock job directly. This avoids coupling Path navigation
    # to the asynchronously loaded facet controls.
    job_743 = admin.get_by_role("button", name=re.compile(r"Day2Actions\s+#743"))
    expect(job_743).to_be_visible()
    job_743.click()
    expect(admin).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    run_url = admin.url
    # Navigate to the Path Explorer view
    admin.goto(run_url.rstrip("/") + "/path")
    return run_url


def test_path_view_synced_main_flow_loop_stepper_and_keyboard(new_context: CreateContextCallback) -> None:
    """Full-slice E2E for the Run Path Explorer on REAL SYNCED mock-AWX data.

    Mock-AWX job 743 has a single play → the main view auto-descends into the play,
    showing tasks directly (including the 'Install packages' loop node from packages.yml).

    Assertions:
      1. Canvas renders; at least one node from the synced run is visible.
      2. Include and loop cards expose explicit enter actions, including in the drawer.
      3. Loop view shows the stepper at "1 / 3" (3 items: nginx/curl/git).
      4. Next-iteration button advances stepper to "2 / 3".
      5. Host scope can be changed with the keyboard.
    """
    ctx: BrowserContext = new_context()
    page = ctx.new_page()
    try:
        _bootstrap_admin(page)
        _ensure_team(page)
        _add_or_open_controller(page)
        _sync_and_wait(page)
        _open_job_743_path(page)

        # 1. Canvas is present; wait for the synced run's nodes to render.
        expect(page.locator('[data-testid="path-canvas"]')).to_be_visible(timeout=10_000)

        # 2. Selecting the rightmost include still opens its drawer, and the drawer offers
        #    the same semantic entry action as the card.
        include_card = page.locator('[data-node-type="include"]').last
        include_card.click()
        drawer = page.locator('[data-testid="path-drawer"]')
        expect(drawer).to_be_visible(timeout=5_000)
        expect(drawer.get_by_role("button", name="Enter packages.yml")).to_be_visible()
        drawer.get_by_role("button", name="Close drawer").click()

        # 3. Enter the include and then the loop through explicit actions.
        page.get_by_role("button", name="Enter packages.yml").click()
        expect(page.get_by_text("Install packages", exact=True)).to_be_visible()
        page.get_by_role("button", name="Enter Install packages").click()
        expect(page.locator('[data-testid="path-stepper"]')).to_be_visible(timeout=5_000)
        expect(page.locator('[data-testid="path-stepper"]')).to_contain_text("1 / 3")

        # 4. Advance to the next iteration.
        page.get_by_role("button", name="Next iteration").click()
        expect(page.locator('[data-testid="path-stepper"]')).to_contain_text("2 / 3")

        # 5. Click any visible node to open the drawer.
        page.locator('[data-testid^="node-"]').first.click()
        expect(page.locator('[data-testid="path-drawer"]')).to_be_visible(timeout=5_000)

        # 6. Native host options support focus plus ArrowDown/Enter selection.
        host_scope = page.get_by_test_id("host-scope-chip")
        host_scope.focus()
        host_scope.press("Enter")
        all_hosts = page.get_by_test_id("host-option-all")
        all_hosts.focus()
        all_hosts.press("ArrowDown")
        page.locator(':focus').press("Enter")
        expect(host_scope).to_contain_text("host-a")
    finally:
        ctx.close()
