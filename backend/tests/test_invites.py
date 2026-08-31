from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import Invite, Team, TeamMember, User


async def test_admin_creates_invite_and_user_accepts(admin_client, db):
    r = await admin_client.post("/api/admin/invites", json={"email": "new@example.com", "role": "user"})
    assert r.status_code == 201
    body = r.json()
    # Slim payload: only the link (which embeds the token) + expiry; no dead fields.
    assert "invite_id" not in body and "token" not in body
    assert "/invite/" in body["link"]
    token = body["link"].rsplit("/", 1)[-1]
    # expires_at must be a parseable ISO datetime (the FE computes the TTL from it),
    # emitted in the API's canonical wire format: tz-aware UTC with a 'Z' suffix.
    assert body["expires_at"].endswith("Z")
    assert datetime.fromisoformat(body["expires_at"]).tzinfo is not None

    # validate endpoint
    info = await admin_client.get(f"/api/invites/{token}")
    assert info.status_code == 200 and info.json()["email"] == "new@example.com"
    assert "role" not in info.json()

    # accept (admin_client's session cookie is ignored by the public accept route)
    acc = await admin_client.post(f"/api/invites/{token}/accept", json={
        "display_name": "Newbie", "password": "brand-new-pass-99",
    })
    assert acc.status_code == 201
    assert acc.json()["email"] == "new@example.com"

    user = await db.scalar(select(User).where(User.email == "new@example.com"))
    general = await db.scalar(select(Team).where(Team.is_default.is_(True)))
    assert await db.scalar(
        select(func.count()).select_from(TeamMember)
        .where(TeamMember.user_id == user.id, TeamMember.team_id == general.id)
    ) == 1


async def test_reused_token_rejected(admin_client, db):
    r = await admin_client.post("/api/admin/invites", json={"email": "once@example.com", "role": "user"})
    token = r.json()["link"].rsplit("/", 1)[-1]
    assert (await admin_client.post(f"/api/invites/{token}/accept",
            json={"display_name": "A", "password": "first-accept-99"})).status_code == 201
    again = await admin_client.post(f"/api/invites/{token}/accept",
            json={"display_name": "B", "password": "second-accept-99"})
    assert again.status_code == 400


async def test_expired_token_rejected(admin_client, db):
    r = await admin_client.post("/api/admin/invites", json={"email": "exp@example.com", "role": "user"})
    token = r.json()["link"].rsplit("/", 1)[-1]
    inv = await db.scalar(select(Invite).where(Invite.email == "exp@example.com"))
    inv.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.flush()
    acc = await admin_client.post(f"/api/invites/{token}/accept",
            json={"display_name": "X", "password": "too-late-pass-99"})
    assert acc.status_code == 400


async def test_garbage_token_rejected(client):
    assert (await client.get("/api/invites/not-a-real-token")).status_code == 400


async def test_non_admin_cannot_create_invite(authed_client):
    r = await authed_client.post("/api/admin/invites", json={"email": "x@example.com", "role": "user"})
    assert r.status_code == 403
