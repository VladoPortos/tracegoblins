import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "backend/tests/fixtures/logs/sample_log-1780472760441.txt"


def _bootstrap_admin(page: Page) -> None:
    # The E2E suite shares ONE live DB. If /setup is still open we create the first
    # admin here; if a prior test already completed setup, the SPA client-side
    # redirects /setup -> /login, so we sign in with the same credentials instead.
    # Either path lands on the "Job logs" dashboard logged in as the admin.
    # We branch on the unique heading rather than page.url, because the React
    # <Navigate> redirect resolves asynchronously (after the setup-status query),
    # so page.url can still read /setup at the moment of the check.
    page.goto("/setup")
    setup_heading = page.get_by_role("heading", name="Create the first administrator")
    login_heading = page.get_by_role("heading", name="Sign in to your workspace")
    expect(setup_heading.or_(login_heading)).to_be_visible()
    if login_heading.is_visible():
        page.get_by_label("Email").fill("admin@example.com")
        page.get_by_label("Password", exact=True).fill("sup3r-s3cret-admin")
        page.get_by_role("button", name="Sign in").click()
    else:
        page.get_by_label("Email").fill("admin@example.com")
        page.get_by_label("Display name").fill("Boss Admin")
        page.get_by_label("Password", exact=True).fill("sup3r-s3cret-admin")
        page.get_by_label("Confirm password").fill("sup3r-s3cret-admin")
        page.get_by_role("button", name="Create admin").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()


def test_upload_parse_statusmap_drawer_delete(page: Page):
    _bootstrap_admin(page)

    # Upload the sample log via the modal (file tab), with a deterministic template name
    # so the resulting card has a stable accessible name to click later.
    page.get_by_role("button", name="Upload log").first.click()  # header button (the empty-state one is also named "Upload log")
    page.get_by_role("button", name="Upload file").click()
    page.get_by_label("Log file").set_input_files(str(SAMPLE))
    page.get_by_label("Template name (optional)").fill("Win deploy")
    page.get_by_role("button", name="Upload & analyze").click()

    # Lands on the Status Map (/runs/:id); the run has one unreachable host (100.70.7.24).
    expect(page).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    expect(page.get_by_text("Status map")).to_be_visible()
    expect(page.get_by_role("button", name="First failure")).to_be_visible()

    # First failure -> drawer opens on the unreachable 'Gathering Facts' with the failure detail.
    page.get_by_role("button", name="First failure").click()
    expect(page.get_by_text("Failure detail")).to_be_visible()
    expect(page.get_by_text("100.70.7.24").first).to_be_visible()

    # Back to My logs; the run card (named by its template) is present.
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()
    card = page.get_by_role("button", name=re.compile("Win deploy"))
    expect(card).to_be_visible()

    # Re-open the run and delete it (the confirm() dialog is auto-accepted), then assert it's gone.
    card.click()
    expect(page).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()
    expect(page.get_by_text("No logs yet")).to_be_visible()
