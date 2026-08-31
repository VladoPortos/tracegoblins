from app.security.cookies import sign_session_id, unsign_session_id


def test_sign_unsign_roundtrip():
    token = sign_session_id("abc123")
    assert token != "abc123"
    assert unsign_session_id(token) == "abc123"


def test_unsign_rejects_tampered():
    token = sign_session_id("abc123")
    assert unsign_session_id(token + "x") is None


def test_unsign_rejects_wrong_key(monkeypatch):
    # Re-sign under a different key by clearing the cached serializer's secret.
    import app.security.cookies as c
    from itsdangerous import URLSafeTimedSerializer
    other = URLSafeTimedSerializer("a-totally-different-secret", salt=c._SALT).dumps("abc123")
    assert unsign_session_id(other) is None
