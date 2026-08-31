import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "backend/tests/fixtures/logs/sample_log-1780472760441.txt"


def _bootstrap_admin(page: Page) -> None:
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


def _upload_personal(page: Page, template: str) -> None:
    page.get_by_role("button", name="Upload log").first.click()
    page.get_by_role("button", name="Upload file").click()
    page.get_by_label("Log file").set_input_files(str(SAMPLE))
    page.get_by_label("Template name (optional)").fill(template)
    page.get_by_role("button", name="Upload & analyze").click()
    expect(page).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()


def test_logs_view_count_table_sort_persist_and_keyboard(page: Page):
    _bootstrap_admin(page)
    _upload_personal(page, "LogsView Probe")

    # Live count shows at least one run (renders "1" + "run" as separate spans → "1run").
    expect(page.get_by_test_id("runs-count")).to_contain_text("run")
    expect(page.get_by_test_id("runs-count")).to_contain_text("1")

    # Default cards view: the run card is present.
    expect(page.get_by_role("button", name=re.compile("LogsView Probe"))).to_be_visible()

    # Toggle to Table: column headers appear.
    page.get_by_role("button", name="Table").click()
    expect(page.get_by_role("columnheader", name="Job")).to_be_visible()
    expect(page.get_by_role("columnheader", name=re.compile("#ID"))).to_be_visible()

    # Activate the default When sort through its native keyboard-focusable button.
    when_header = page.get_by_role("columnheader", name=re.compile("When"))
    expect(when_header).to_have_attribute("aria-sort", "descending")
    when_sort = page.get_by_role("button", name=re.compile(r"^When"))
    when_sort.focus()
    when_sort.press("Enter")
    expect(when_header).to_have_attribute("aria-sort", "ascending")

    # Persist across navigation: leave to KB, come back via the Logs nav button.
    page.get_by_role("link", name="Knowledge base").click()
    expect(page).to_have_url(re.compile(r"/kb"))
    page.get_by_role("button", name="Logs", exact=True).click()
    expect(page.get_by_role("columnheader", name="Job")).to_be_visible()  # still Table

    # Persist across a full refresh.
    page.reload()
    expect(page.get_by_role("columnheader", name="Job")).to_be_visible()

    # Cleanup: open the run through its native link using only the keyboard, then delete it.
    run_link = page.get_by_role("link", name="LogsView Probe")
    run_link.focus()
    run_link.press("Enter")
    expect(page).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()
    expect(page.get_by_text("No logs yet")).to_be_visible()
