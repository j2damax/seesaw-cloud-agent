"""API key middleware — all protected routes must reject missing or wrong keys."""


def test_story_no_key_returns_401(client, valid_payload):
    r = client.post("/story/generate", json=valid_payload)
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized"}


def test_story_wrong_key_returns_401(client, valid_payload):
    r = client.post(
        "/story/generate",
        json=valid_payload,
        headers={"X-SeeSaw-Key": "wrong-key"},
    )
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized"}


def test_model_no_key_returns_401(client):
    r = client.get("/model/latest")
    assert r.status_code == 401


def test_session_get_no_key_returns_401(client):
    r = client.get("/session/some-session-id")
    assert r.status_code == 401


def test_session_delete_no_key_returns_401(client):
    r = client.delete("/session/some-session-id")
    assert r.status_code == 401
