import pytest
from playwright.sync_api import Page, expect
from pytest_playwright.pytest_playwright import CreateContextCallback

pytestmark = pytest.mark.e2e

# Run against a FRESH stack (empty DB) so /setup is unlocked.


def test_full_onboarding(page: Page, new_context: CreateContextCallback):
    # 1. First-run setup wizard creates the first admin.
    page.goto("/setup")
    page.get_by_label("Email").fill("admin@example.com")
    page.get_by_label("Display name").fill("Boss Admin")
    page.get_by_label("Password", exact=True).fill("sup3r-s3cret-admin")
    # Mismatched confirmation must be rejected client-side (no lockout from a typo'd password).
    page.get_by_label("Confirm password").fill("sup3r-s3cret-admin-TYPO")
    page.get_by_role("button", name="Create admin").click()
    expect(page.get_by_text("Passwords do not match.")).to_be_visible()
    page.get_by_label("Confirm password").fill("sup3r-s3cret-admin")
    page.get_by_role("button", name="Create admin").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()

    # 2. Create a team.
    page.goto("/admin/teams")
    page.get_by_role("button", name="New team").click()
    page.get_by_label("Team name").fill("Platform")
    page.get_by_role("button", name="Create").click()
    # The new team renders as a card button (the page's static h1 also contains the
    # word "platform", so assert on the specific team-card button, not loose text).
    expect(page.get_by_role("button", name="Platform")).to_be_visible()

    # 3. Invite a user; capture the copyable link.
    page.goto("/admin/users")
    page.get_by_role("button", name="Invite user").click()
    page.get_by_label("Email").fill("member@example.com")
    page.get_by_role("button", name="Generate link").click()
    invite_link = page.get_by_test_id("invite-link").input_value()
    assert "/invite/" in invite_link

    # 4. Second user accepts in an ISOLATED context (no admin cookies).
    user_ctx = new_context()
    user_page = user_ctx.new_page()
    user_page.goto(invite_link)
    user_page.get_by_label("Display name").fill("New Member")
    user_page.get_by_label("Password", exact=True).fill("member-pass-1234")
    user_page.get_by_label("Confirm password").fill("member-pass-1234")
    user_page.get_by_role("button", name="Accept invite").click()
    expect(user_page.get_by_role("heading", name="Job logs")).to_be_visible()

    # 5. New user is a member of >=1 team (General) — visible on the profile.
    user_page.goto("/settings")
    expect(user_page.get_by_text("General")).to_be_visible()

    # 6. Sign out (revocable session), then confirm self-register is impossible:
    #    the logged-out /login page offers no signup affordance.
    user_page.get_by_role("button", name="Account menu").click()
    user_page.get_by_role("menuitem", name="Sign out").click()
    expect(user_page.get_by_role("button", name="Sign in")).to_be_visible()
    user_page.goto("/login")
    expect(user_page.get_by_text("Ask an administrator for an invite")).to_be_visible()

    # 7. Team membership via the SPA (admin context): add the new member to the Platform team,
    #    exercising the §14 membership surface end-to-end (not just in unit tests).
    page.goto("/admin/teams")
    page.get_by_role("button", name="Platform").click()
    page.get_by_label("Add member").select_option(label="New Member (member@example.com)")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_text("New Member")).to_be_visible()

    user_ctx.close()
