"""
E2E tests for the 2FA (TOTP) enrolment and two-step login flow.

Exercises:
  1. Enrol TOTP via Settings → Security
  2. Log out
  3. Two-step login with a TOTP code
  4. Log out, then log in with a recovery code

Run after all other suites (order = 5) so the admin's totp_enabled=True state
does not perturb earlier files' clean-slate assertions on the shared database.
"""

import re
import time

import pyotp
import pytest
from playwright.sync_api import Page, expect
from pytest_playwright.pytest_playwright import CreateContextCallback

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "sup3r-s3cret-admin"

# Stored between steps (module-level so sub-functions can write/read them).
_totp_secret: str = ""
_recovery_code: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _complete_totp_challenge(page: Page, secret: str) -> None:
    """If the page is showing the 2FA verify step, complete it with TOTP."""
    verify_heading = page.get_by_role("heading", name="Verify your identity")
    if verify_heading.is_visible():
        code = pyotp.TOTP(secret).now()
        page.get_by_label("Authenticator code").fill(code)
        page.get_by_role("button", name="Verify").click()
        expect(page.get_by_role("heading", name="Job logs")).to_be_visible(timeout=10_000)


def _bootstrap_admin(page: Page, totp_secret: str = "") -> None:
    """
    Setup-or-login — identical pattern to test_awx_sync.py, with an
    additional branch for the 2FA challenge (for idempotent reruns).
    """
    page.goto("/setup")
    setup_heading = page.get_by_role("heading", name="Create the first administrator")
    login_heading = page.get_by_role("heading", name="Sign in to your workspace")
    expect(setup_heading.or_(login_heading)).to_be_visible()
    if login_heading.is_visible():
        page.get_by_label("Email").fill(ADMIN_EMAIL)
        page.get_by_label("Password", exact=True).fill(ADMIN_PW)
        page.get_by_role("button", name="Sign in").click()
        # Handle possible 2FA challenge (idempotent rerun after enrolment)
        if totp_secret:
            _complete_totp_challenge(page, totp_secret)
    else:
        page.get_by_label("Email").fill(ADMIN_EMAIL)
        page.get_by_label("Display name").fill("Boss Admin")
        page.get_by_label("Password", exact=True).fill(ADMIN_PW)
        page.get_by_label("Confirm password").fill(ADMIN_PW)
        page.get_by_role("button", name="Create admin").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible(timeout=10_000)


def _logout(page: Page) -> None:
    """Open the Account menu and click Sign out."""
    page.get_by_role("button", name="Account menu").click()
    page.get_by_role("menuitem", name="Sign out").click()
    expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible(timeout=10_000)


def _safe_totp_code(secret: str) -> str:
    """
    Return a current TOTP code, sleeping into a new 30s window first if
    fewer than 3 seconds remain in the current one (avoids race at boundary).
    """
    secs_remaining = 30 - (time.time() % 30)
    if secs_remaining < 3:
        time.sleep(secs_remaining + 1)
    return pyotp.TOTP(secret).now()


def _totp_code_after(secret: str, prev_step: int) -> str:
    """Return a TOTP code from a 30s step STRICTLY LATER than prev_step.

    The backend's replay guard (totp_last_used_step) rejects a step <= the last used one —
    including the code burned at enrollment — so a post-enrollment login MUST use a later
    step. Waits at most one window (~30s).
    """
    while int(time.time()) // 30 <= prev_step:
        time.sleep(1)
    return pyotp.TOTP(secret).now()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_enroll_totp_and_login_with_totp_then_recovery(new_context: CreateContextCallback):
    """
    Full 2FA journey:
      1. Enrol TOTP (Settings → Security).
      2. Capture the first recovery code shown.
      3. Log out.
      4. Log back in with a fresh TOTP code (first 2FA login verify).
      5. Log out.
      6. Log back in with the captured recovery code.
    """
    ctx = new_context()
    page = ctx.new_page()
    try:
        # ── 1. Bootstrap ──────────────────────────────────────────────────────
        _bootstrap_admin(page)

        # ── 2. Navigate to Security settings ─────────────────────────────────
        page.goto("/settings/security")
        expect(page.get_by_role("heading", name="Settings")).to_be_visible(timeout=10_000)

        # Wait for the security section to fully load (either enrolled or not).
        # The two possible stable states are the "Enable" button (not enrolled)
        # or the "2FA is enabled" text (already enrolled).
        enrolled_text = page.get_by_text("2FA is enabled on your account.")
        enable_btn_initial = page.get_by_role("button", name="Enable two-factor authentication")
        expect(enrolled_text.or_(enable_btn_initial)).to_be_visible(timeout=10_000)

        # If 2FA is already enabled skip (caller should reset DB)
        if enrolled_text.is_visible():
            pytest.skip("Admin already has 2FA enabled — reset DB and rerun.")

        # ── 3. Start enrolment ────────────────────────────────────────────────
        enable_btn_initial.click()

        # Wait for the TOTP secret element (API call returns provisioning URI)
        secret_el = page.get_by_test_id("totp-secret")
        expect(secret_el).to_be_visible(timeout=10_000)
        raw_secret = secret_el.inner_text().strip().replace(" ", "")
        assert len(raw_secret) >= 16, f"Secret looks wrong: {raw_secret!r}"

        # ── 4. Enter the 6-digit code and click Enable ────────────────────────
        enroll_code = _safe_totp_code(raw_secret)
        enroll_step = int(time.time()) // 30  # the step burned by enrollment (replay guard)
        page.get_by_label("Verification code").fill(enroll_code)

        # The Enable button is inside a row next to the Field; click it.
        # There are two "Enable" buttons in the DOM (one hidden, one visible).
        # Use the one that is enabled (not disabled).
        enable_btn = page.get_by_role("button", name="Enable", exact=True)
        expect(enable_btn).to_be_enabled(timeout=5_000)
        enable_btn.click()

        # ── 5. Recovery codes panel appears — capture codes before useMe re-query ─
        # When useMfaEnable succeeds it sets recoveryCodes React state (showing the panel),
        # but useMe simultaneously invalidates and re-fetches; once totp_enabled=true lands,
        # SecuritySettings switches from <EnrollSection> (which owns the recoveryCodes state)
        # to <EnrolledSection>, destroying the state and the panel.  The window is short.
        #
        # Strategy: poll page.content() until we find a code-shaped string, rather than
        # waiting for a DOM locator that may already be gone by the time Playwright checks.
        code_pattern = re.compile(r"[a-z2-9]{5}-[a-z2-9]{5}")
        recovery_code: str = ""
        deadline = time.time() + 15  # 15 s max
        while time.time() < deadline:
            text = page.inner_text("body")
            m = code_pattern.search(text)
            if m:
                recovery_code = m.group(0)
                break
            time.sleep(0.2)
        assert recovery_code, "Recovery codes panel never showed a xxxxx-xxxxx code within 15 s"

        # If the Done button is still visible, click it (the panel may still be mounted).
        done_btn = page.get_by_role("button", name="Done")
        if done_btn.is_visible():
            done_btn.click()

        # Either way, enrolled state should now be visible.
        expect(page.get_by_text("2FA is enabled on your account.")).to_be_visible(timeout=10_000)

        # ── 6. Log out ────────────────────────────────────────────────────────
        _logout(page)

        # ── 7. Two-step login — TOTP code ─────────────────────────────────────
        # The enrol 'Enable' step does NOT consume the replay guard (only
        # POST /auth/login/verify does).  So we can use a fresh code here.
        page.goto("/login")
        expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()
        page.get_by_label("Email").fill(ADMIN_EMAIL)
        page.get_by_label("Password", exact=True).fill(ADMIN_PW)
        page.get_by_role("button", name="Sign in").click()

        # 2FA challenge step
        expect(page.get_by_role("heading", name="Verify your identity")).to_be_visible(timeout=10_000)

        totp_login_code = _totp_code_after(raw_secret, enroll_step)
        page.get_by_label("Authenticator code").fill(totp_login_code)
        page.get_by_role("button", name="Verify").click()

        expect(page.get_by_role("heading", name="Job logs")).to_be_visible(timeout=10_000)

        # ── 8. Log out ────────────────────────────────────────────────────────
        _logout(page)

        # ── 9. Two-step login — RECOVERY CODE ────────────────────────────────
        # We must use a DIFFERENT step for the recovery code login to avoid
        # TOTP replay guard (recovery codes bypass TOTP anyway).
        page.goto("/login")
        expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()
        page.get_by_label("Email").fill(ADMIN_EMAIL)
        page.get_by_label("Password", exact=True).fill(ADMIN_PW)
        page.get_by_role("button", name="Sign in").click()

        expect(page.get_by_role("heading", name="Verify your identity")).to_be_visible(timeout=10_000)

        # Toggle to recovery code mode
        page.get_by_role("button", name="Use a recovery code instead").click()
        expect(page.get_by_label("Recovery code")).to_be_visible(timeout=5_000)

        page.get_by_label("Recovery code").fill(recovery_code)
        page.get_by_role("button", name="Verify").click()

        # Should land on Job logs after successful recovery-code login
        expect(page.get_by_role("heading", name="Job logs")).to_be_visible(timeout=10_000)

    finally:
        ctx.close()
