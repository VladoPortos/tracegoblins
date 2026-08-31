import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, expect
from pytest_playwright.pytest_playwright import CreateContextCallback

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "backend/tests/fixtures/logs/sample_log-1780472760441.txt"

# Distinct, deterministic identities for this flow. The E2E suite shares ONE live DB,
# so we branch idempotently in _bootstrap_admin (setup-or-login) exactly like
# test_upload_status_map.py. Emails use @example.com (the dockerized app's allowed TLDs).
ADMIN_EMAIL = "admin@example.com"
ADMIN_PW = "sup3r-s3cret-admin"
B_EMAIL = "collab-b@example.com"
B_NAME = "Bea Collaborator"
B_PW = "collab-b-passw0rd"
TEAM_NAME = "Falcon Squad"
# A template name unique to THIS test so the run card / inbox copy is greppable and
# does not collide with test_upload_status_map.py's "Win deploy" run on the shared DB.
RUN_TPL = "Collab Deploy"
TEAM_RUN_TPL = "Team Deploy"


def _bootstrap_admin(page: Page) -> None:
    # Setup-or-login for the admin (A). Branch on the unique auth heading, NOT page.url,
    # because the React <Navigate> redirect resolves async (after the setup-status query).
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


def _logout(page: Page) -> None:
    page.get_by_role("button", name="Account menu").click()
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()


def _login_as(page: Page, email: str, password: str) -> None:
    page.goto("/login")
    expect(page.get_by_role("heading", name="Sign in to your workspace")).to_be_visible()
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Job logs")).to_be_visible()


def _ensure_user_b_and_team(admin: Page) -> None:
    # Idempotent on the shared DB: only create B + team T if they're absent.
    # Drives the SHIPPED M1 admin UI (invite is link-based, D6; the invitee sets their
    # own display name + password on the accept page — the invite modal only takes email).
    # ----- Invite B (admin-invite-only onboarding, D5) and set B's account via the link.
    admin.get_by_role("button", name="Admin").click()
    expect(admin.get_by_role("button", name="Invite user")).to_be_visible()
    # The user list loads async; wait for the always-present admin row before the
    # idempotency check below, or is_visible() snapshots an empty list (false negative).
    expect(admin.get_by_text(ADMIN_EMAIL)).to_be_visible()
    if not admin.get_by_text(B_EMAIL).is_visible():
        admin.get_by_role("button", name="Invite user").click()
        admin.get_by_label("Email").fill(B_EMAIL)
        admin.get_by_role("button", name="Generate link").click()
        # The invite is link-based (D6): a copyable /invite/<token> URL is shown.
        invite_url = admin.get_by_test_id("invite-link").input_value()
        # Drive the accept flow on a clean, isolated context we discard (sharing A's
        # context would clobber A's session).
        invite_page = admin.context.browser.new_context(ignore_https_errors=True).new_page()
        invite_page.goto(invite_url)
        expect(invite_page.get_by_role("heading", name="Set up your account")).to_be_visible()
        invite_page.get_by_label("Display name").fill(B_NAME)
        invite_page.get_by_label("Password", exact=True).fill(B_PW)
        invite_page.get_by_label("Confirm password").fill(B_PW)
        invite_page.get_by_role("button", name="Accept invite").click()
        expect(invite_page.get_by_role("heading", name="Job logs")).to_be_visible()
        invite_page.context.close()
        admin.get_by_role("button", name="Done").click()  # close the invite modal
        # B was just created in a SEPARATE browser context, so A's cached admin-users
        # query (staleTime) can't know about B yet. Hard-reload to refetch so B shows up
        # in the member picker below.
        admin.reload()
        expect(admin.get_by_role("button", name="Invite user")).to_be_visible()
    # ----- Create team T and add B as a member (team renders as a card; clicking opens
    # the team-detail modal where members are managed).
    admin.get_by_role("button", name="Teams").click()
    # The teams grid loads async; wait for the always-present default "General" team card
    # before the idempotency check, or is_visible() snapshots an empty grid (false
    # negative) and we'd wrongly try to re-create the team.
    expect(admin.get_by_role("button", name="General")).to_be_visible()
    if not admin.get_by_role("button", name=TEAM_NAME).is_visible():
        admin.get_by_role("button", name="New team").click()
        admin.get_by_label("Team name").fill(TEAM_NAME)
        admin.get_by_role("button", name="Create").click()
        expect(admin.get_by_role("button", name=TEAM_NAME)).to_be_visible()
    admin.get_by_role("button", name=TEAM_NAME).click()
    dlg = admin.get_by_role("dialog")
    expect(dlg).to_be_visible()
    # The picker contains only NON-members. On an idempotent second setup pass every
    # known user may already belong to the team, leaving only the placeholder option.
    # Visibility is therefore the stable readiness contract; each membership check below
    # safely does nothing when its option is absent.
    picker = dlg.get_by_label("Add member")
    expect(picker).to_be_visible()

    def _ensure_member(name: str, email: str) -> None:
        # The picker is a <select> whose options read "Display name (email)". A NON-member
        # appears as an option; a current member does not. (We must detect membership via
        # the option's presence — the email string also appears in the option text, so a
        # plain dlg.get_by_text(email) would false-positive for a non-member.)
        option = picker.get_by_role("option", name=f"{name} ({email})")
        if option.count() > 0:
            picker.select_option(label=f"{name} ({email})")
            dlg.get_by_role("button", name="Add", exact=True).click()
            # After adding, the user leaves the picker and joins the members list.
            expect(picker.get_by_role("option", name=f"{name} ({email})")).to_have_count(0)

    _ensure_member(B_NAME, B_EMAIL)
    # Add A (the admin) too. Per spec §5 the Share modal's team picker offers only the
    # REQUESTER's teams (me.teams), so the owner must belong to T to share T.
    _ensure_member("Boss Admin", ADMIN_EMAIL)
    dlg.get_by_role("button", name="Close").click()
    # me.teams is cached (staleTime); reload so the Share picker sees A's new T membership.
    admin.reload()
    admin.goto("/")
    expect(admin.get_by_role("heading", name="Job logs")).to_be_visible()


def _upload(page: Page, template: str, save_to: str | None) -> str:
    # Upload the sample log via the modal (file tab). `save_to` None -> Personal default;
    # otherwise the team display name in the "Save to" picker. Returns the run id (from URL).
    page.get_by_role("button", name="Upload log").first.click()
    page.get_by_role("button", name="Upload file").click()
    page.get_by_label("Log file").set_input_files(str(SAMPLE))
    page.get_by_label("Template name (optional)").fill(template)
    if save_to is not None:
        page.get_by_label("Save to").select_option(label=save_to)
    page.get_by_role("button", name="Upload & analyze").click()
    expect(page).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
    expect(page.get_by_text("Status map")).to_be_visible()
    m = re.search(r"/runs/([0-9a-f-]+)", page.url)
    assert m, f"no run id in url {page.url}"
    return m.group(1)


def test_share_annotate_comment_mention_inbox_reply(new_context: CreateContextCallback):
    # Two independent cookie jars: A (admin) and B (invited user). Use the pytest-playwright
    # `new_context` fixture (not raw browser.new_context) so each context inherits base_url
    # from browser_context_args — relative goto("/setup") etc. resolve against the live stack.
    ctx_a: BrowserContext = new_context()
    ctx_b: BrowserContext = new_context()
    a = ctx_a.new_page()
    b = ctx_b.new_page()
    try:
        a.add_init_script(r"""
          const realFetch = window.fetch.bind(window);
          let delayed = false;
          window.fetch = (...args) => {
            const request = args[0];
            const init = args[1] || {};
            const url = typeof request === 'string' ? request : request.url;
            if (!delayed && init.method === 'POST' && /\/api\/runs\/[^/]+\/shares$/.test(url)) {
              delayed = true;
              return new Promise((resolve, reject) => {
                setTimeout(() => realFetch(...args).then(resolve, reject), 500);
              });
            }
            return realFetch(...args);
          };
        """)
        _bootstrap_admin(a)
        _ensure_user_b_and_team(a)

        # ---- A uploads a PERSONAL run, then shares it with user B AND team T. ----
        run_id = _upload(a, RUN_TPL, save_to=None)

        a.get_by_role("button", name="Share").click()
        dlg = a.get_by_role("dialog")
        expect(dlg.get_by_role("heading", name=re.compile("Share"))).to_be_visible()
        # Share with user B — the combined "Add people or teams" picker shares on option click.
        search = dlg.get_by_label("Add people or teams")
        search.fill(B_EMAIL)
        with a.expect_response(
            lambda response: re.search(r"/api/runs/[^/]+/shares$", response.url) is not None
            and response.request.method == "POST"
        ):
            dlg.get_by_role("option", name=re.compile(re.escape(B_EMAIL))).click()
            search.fill(TEAM_NAME)
        # The first delayed POST has completed; its success callback must not erase
        # the query already entered for the next recipient.
        a.wait_for_timeout(100)
        expect(search).to_have_value(TEAM_NAME)
        expect(dlg.get_by_role("option", name=re.compile(re.escape(TEAM_NAME)))).to_be_visible()
        expect(dlg.get_by_text(B_EMAIL)).to_be_visible()  # B now appears in the current-shares list
        # Share with team T — same combined picker, by team name.
        dlg.get_by_role("option", name=re.compile(re.escape(TEAM_NAME))).click()
        expect(dlg.get_by_text(TEAM_NAME)).to_be_visible()
        a.get_by_role("button", name="Close").click()

        # ---- B logs in; sees the run under BOTH Shared-with-me AND Team-workspace. ----
        _login_as(b, B_EMAIL, B_PW)
        b.get_by_role("button", name="Shared with me").click()
        shared_card = b.get_by_role("button", name=re.compile(re.escape(RUN_TPL)))
        expect(shared_card).to_be_visible()
        b.get_by_role("button", name="Team workspace").click()
        # TEAM_NAME appears twice on this page (the team group header AND the card's team
        # chip), so scope to the first (the group header) to avoid a strict-mode violation.
        expect(b.get_by_text(TEAM_NAME).first).to_be_visible()  # team group header
        expect(b.get_by_role("button", name=re.compile(re.escape(RUN_TPL)))).to_be_visible()

        # ---- B opens the run, opens the failing task, annotates (needs-fix) + comments @A. ----
        b.get_by_role("button", name="Shared with me").click()
        b.get_by_role("button", name=re.compile(re.escape(RUN_TPL))).click()
        expect(b).to_have_url(re.compile(r"/runs/[0-9a-f-]+"))
        b.get_by_role("button", name="First failure").click()   # opens the drawer on the failure
        expect(b.get_by_text("Failure detail")).to_be_visible()

        # Annotation: note + the needs-fix tag.
        b.get_by_role("button", name="Add annotation").click()
        b.get_by_label("Annotation note").fill("Looks like the host is unreachable — needs a fix.")
        b.get_by_role("button", name="needs-fix").click()       # tag toggle
        b.get_by_role("button", name="Save annotation").click()
        expect(b.get_by_text("Looks like the host is unreachable")).to_be_visible()
        expect(b.get_by_text("needs-fix")).to_be_visible()

        # Comment that @-mentions A. Typing "@" then the admin name triggers the autocomplete.
        composer = b.get_by_label("Add a comment")
        composer.fill("@")
        composer.type("Boss")                                   # narrows the mentionable list to "Boss Admin"
        b.get_by_role("option", name=re.compile("Boss Admin")).click()
        composer.type(" please take a look")
        b.get_by_role("button", name="Post comment").click()
        expect(b.get_by_text("please take a look")).to_be_visible()

        # ---- A's bell shows an unread badge; A opens the inbox and clicks the mention. ----
        a.goto("/")
        bell = a.get_by_role("button", name="Notifications")
        # The unread badge polls on focus/interval; reload to force the count query, then assert.
        expect(a.get_by_test_id("unread-badge")).to_be_visible()
        bell.click()
        # The mention item names the actor + task; clicking deep-links to /runs/{run_id} + opens the drawer.
        mention_item = a.get_by_role("menuitem", name=re.compile(f"{B_NAME}.*comment"))
        expect(mention_item).to_be_visible()
        mention_item.click()
        expect(a).to_have_url(re.compile(rf"/runs/{re.escape(run_id)}"))

        # ---- A lands on the task drawer, sees B's annotation + comment, and replies. ----
        expect(a.get_by_text("Looks like the host is unreachable")).to_be_visible()
        expect(a.get_by_text("please take a look")).to_be_visible()
        a.get_by_role("button", name="Reply").first.click()
        reply = a.get_by_label("Reply")
        reply.fill("On it — checking the network path now.")
        a.get_by_role("button", name="Post reply").click()
        expect(a.get_by_text("On it — checking the network path")).to_be_visible()

        # After opening the inbox the mention is marked read -> badge clears.
        a.goto("/")
        expect(a.get_by_test_id("unread-badge")).not_to_be_visible()
    finally:
        ctx_a.close()
        ctx_b.close()


def test_upload_to_team_appears_in_team_workspace(new_context: CreateContextCallback):
    # A uploads a run directly to team T; B sees it in the Team workspace (not in B's My logs).
    # Use the `new_context` fixture so contexts inherit base_url (relative goto resolves).
    ctx_a: BrowserContext = new_context()
    ctx_b: BrowserContext = new_context()
    a = ctx_a.new_page()
    b = ctx_b.new_page()
    try:
        _bootstrap_admin(a)
        _ensure_user_b_and_team(a)

        # A uploads straight to the team via the "Save to" picker.
        _upload(a, TEAM_RUN_TPL, save_to=TEAM_NAME)
        a.get_by_role("button", name="Back").click()
        expect(a.get_by_role("heading", name="Job logs")).to_be_visible()

        # B sees the team run under Team workspace, grouped under the team header...
        _login_as(b, B_EMAIL, B_PW)
        b.get_by_role("button", name="Team workspace").click()
        # TEAM_NAME shows in both the group header and the card chip → scope to the first.
        expect(b.get_by_text(TEAM_NAME).first).to_be_visible()
        expect(b.get_by_role("button", name=re.compile(re.escape(TEAM_RUN_TPL)))).to_be_visible()

        # ...but NOT in B's "My logs" (B is not the uploader).
        b.get_by_role("button", name="My logs").click()
        expect(b.get_by_role("button", name=re.compile(re.escape(TEAM_RUN_TPL)))).to_have_count(0)
    finally:
        ctx_a.close()
        ctx_b.close()
