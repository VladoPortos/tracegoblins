from app.security.cookies import sign_pending_id, unsign_pending_id


def test_pending_cookie_roundtrip():
    token = sign_pending_id("abc-123")
    assert unsign_pending_id(token) == "abc-123"
    assert unsign_pending_id("garbage") is None
