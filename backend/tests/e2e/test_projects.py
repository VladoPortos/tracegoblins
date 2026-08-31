"""E2E test for the Projects page (M2 Projects subsystem).

Runs AFTER test_awx_sync.py (order 4) in the shared e2e stack. By the time this
test runs the mock AWX controller is already created and synced, so:
  - Project id 10 ("Day2Actions") is mirrored in the DB (mock_awx_data.PROJECTS).
  - All 3 synced runs (743/744/745) are auto-linked to that project via the
    job-detail summary_fields.project.id == 10 match.

Scenario:
  1. Log in as admin (setup-or-login — idempotent on the shared DB).
  2. /projects → mirrored project card is listed.
  3. Open project → "Linked runs (N)" heading with N ≥ 1 is visible.
  4. Upload a plain YAML file via the non-folder file input.
  5. "Uploaded 1 file(s)." confirmation appears.
  6. Switch ref selector to "Uploaded files" → site.yml appears in the tree.
  7. Click site.yml → CodeMirror viewer renders the file content.

NOTE: This test requires the isolated docker-compose.e2e.yml stack (mock-awx sidecar +
app + db). A parse-only smoke check runs in CI without Docker via:
    python -c "import ast; ast.parse(open('tests/e2e/test_projects.py').read())"
"""
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "sup3r-s3cret-admin"
MEMBER_EMAIL = "awx-b@example.com"
MEMBER_PW = "awx-b-passw0rd"


def _bootstrap_admin(page: Page) -> None:
    """Setup-or-login (idempotent on the shared DB).

    If the setup wizard has not yet run (first test file), it creates the admin.
    Otherwise it logs in with the existing admin credentials.
    """
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


def _login_as_member(page: Page) -> None:
    page.goto("/login")
    expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()
    page.get_by_label("Email").fill(MEMBER_EMAIL)
    page.get_by_label("Password", exact=True).fill(MEMBER_PW)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()


def test_project_member_can_refresh_metadata_without_admin_controls(page: Page) -> None:
    """A controller-team member can refresh metadata without gaining Git/upload controls."""
    _login_as_member(page)
    page.goto("/projects")
    page.get_by_role("button", name=re.compile(r"Day2Actions", re.I)).first.click()
    expect(page).to_have_url(re.compile(r"/projects/[0-9a-f-]+"))

    refresh = page.get_by_role("button", name="Refresh metadata")
    expect(refresh).to_be_visible()
    expect(page.get_by_role("button", name="Link git")).to_have_count(0)
    expect(page.get_by_role("button", name="Refresh source")).to_have_count(0)
    expect(page.locator('input[type="file"]')).to_have_count(0)
    with page.expect_response(
        lambda response: response.url.endswith("/refresh-mirror")
        and response.request.method == "POST"
    ):
        refresh.click()


def test_projects_mirror_linked_runs_and_upload(page: Page) -> None:
    """Full-slice E2E for the Projects page on REAL SYNCED mock-AWX data.

    mock_awx_data.PROJECTS has project id=10 ("Day2Actions"); mock job details
    reference summary_fields.project.id=10, so all 3 synced runs auto-link to it.

    Assertions:
      1. /projects lists the mirrored project card by name.
      2. Opening the project shows "Linked runs (N)" with N ≥ 1.
      3. Uploading site.yml via the plain (non-folder) file input succeeds.
      4. Switching the ref selector to "Uploaded files" shows site.yml in the tree.
      5. Clicking site.yml renders its content in the CodeMirror viewer.
    """
    _bootstrap_admin(page)

    # ------------------------------------------------------------------
    # 1. Projects page — the mirrored "Day2Actions" project card is present.
    # ------------------------------------------------------------------
    page.goto("/projects")
    project_btn = page.get_by_role("button", name=re.compile(r"Day2Actions", re.I)).first
    expect(project_btn).to_be_visible(timeout=8_000)

    # ------------------------------------------------------------------
    # 2. Open the project → URL changes to /projects/<uuid>; "Linked runs"
    #    heading shows count ≥ 1 (3 runs synced by test_awx_sync.py are
    #    auto-linked because their job detail references project id 10).
    # ------------------------------------------------------------------
    project_btn.click()
    expect(page).to_have_url(re.compile(r"/projects/[0-9a-f-]+"))
    expect(page.get_by_role("button", name="Refresh metadata")).to_be_visible()
    expect(page.get_by_role("button", name="Link git")).to_be_visible()
    # "Linked runs (N)" is an <h3> rendered by ProjectDetail
    expect(page.get_by_text(re.compile(r"Linked runs \([1-9]\d*\)", re.I))).to_be_visible(
        timeout=8_000
    )

    # ------------------------------------------------------------------
    # 3 + 4. Upload via the plain (non-folder) file input.
    #
    # UploadDropzone renders TWO hidden <input type="file"> elements:
    #   - folderInput  has  webkitdirectory=""  → directory picker
    #   - fileInput    has  NO webkitdirectory  → plain file picker (target this)
    #
    # Playwright can set files on display:none inputs; the onChange handler
    # fires and POSTs to /api/projects/{id}/uploads.
    # ------------------------------------------------------------------
    file_input = page.locator('input[type="file"]:not([webkitdirectory])').first
    file_input.set_input_files([
        {
            "name": "site.yml",
            "mimeType": "text/yaml",
            "buffer": b"- hosts: all\n  gather_facts: true\n  tasks: []\n",
        }
    ])
    # "Uploaded N file(s)." confirmation rendered by UploadDropzone
    expect(page.get_by_text(re.compile(r"Uploaded \d+ file", re.I))).to_be_visible(
        timeout=10_000
    )

    # ------------------------------------------------------------------
    # 5. Switch ref selector to "Uploaded files" → tree populates with
    #    site.yml (via GET /api/projects/{id}/tree?ref=uploads&path=).
    # ------------------------------------------------------------------
    page.locator('select[aria-label="Source revision"]').select_option(value="uploads")
    site_btn = page.get_by_role("button", name=re.compile(r"site\.yml", re.I)).first
    expect(site_btn).to_be_visible(timeout=8_000)

    # ------------------------------------------------------------------
    # 6. Click site.yml → fetchProjectBlob resolves; OutputViewer (CodeMirror)
    #    renders the file content.  Assert the first content line is visible.
    # ------------------------------------------------------------------
    site_btn.click()
    expect(page.get_by_text(re.compile(r"- hosts: all", re.I))).to_be_visible(timeout=8_000)
