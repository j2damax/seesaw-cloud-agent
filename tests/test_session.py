"""GET + DELETE /session/{id} — retrieval, not-found, delete, and idempotency."""
from unittest.mock import AsyncMock, patch


def test_get_existing_session_returns_200(client, auth_headers, mock_firestore):
    r = client.get("/session/test-session-00000000", headers=auth_headers)
    assert r.status_code == 200


def test_get_existing_session_has_expected_fields(client, auth_headers, mock_firestore):
    r = client.get("/session/test-session-00000000", headers=auth_headers)
    body = r.json()
    assert "session_id" in body
    assert "beats" in body
    assert isinstance(body["beats"], list)


def test_get_unknown_session_returns_404(client, auth_headers, mock_firestore):
    mock_firestore["get_session"].return_value = None
    r = client.get("/session/does-not-exist", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "Session not found"


def test_delete_session_returns_deleted_true(client, auth_headers, mock_firestore):
    r = client.delete("/session/test-session-00000000", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"deleted": True}


def test_delete_unknown_session_is_idempotent(client, auth_headers, mock_firestore):
    """DELETE on a non-existent session must still return 200 (GDPR erasure is idempotent)."""
    r = client.delete("/session/does-not-exist", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"deleted": True}


def test_get_after_delete_returns_404(client, auth_headers):
    """After a DELETE, a subsequent GET must return 404."""
    session_id = "ephemeral-session-id"

    with (
        patch("app.routers.session.get_session", new_callable=AsyncMock) as mock_get,
        patch("app.routers.session.delete_session", new_callable=AsyncMock),
    ):
        mock_get.side_effect = [
            {"session_id": session_id, "child_age": 5, "objects": [], "beat_count": 0, "created_at": None, "beats": []},
            None,  # second call simulates post-delete state
        ]

        r1 = client.get(f"/session/{session_id}", headers={"X-SeeSaw-Key": "test-key"})
        assert r1.status_code == 200

        client.delete(f"/session/{session_id}", headers={"X-SeeSaw-Key": "test-key"})

        r2 = client.get(f"/session/{session_id}", headers={"X-SeeSaw-Key": "test-key"})
        assert r2.status_code == 404
