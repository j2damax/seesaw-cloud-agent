"""
Privacy contract tests.

Verifies that no forbidden data (transcript content, child_name) appears in
server-side logs or Firestore writes. This suite serves as dissertation evidence
that the privacy boundary is enforced structurally, not just by convention.
"""
import logging


def test_transcript_not_stored_in_firestore(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    """transcript must never be passed to create_session — it is not a permitted Firestore field."""
    valid_payload["transcript"] = "secret transcript content"
    client.post("/story/generate", json=valid_payload, headers=auth_headers)

    # create_session signature: (session_id, child_age, objects, scene)
    call_args = mock_firestore["create_session"].call_args
    assert call_args is not None
    assert "secret transcript content" not in str(call_args)


def test_child_name_not_stored_in_firestore(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    """child_name must never be passed to create_session — it is not a permitted Firestore field."""
    valid_payload["child_name"] = "UniqueChildName"
    client.post("/story/generate", json=valid_payload, headers=auth_headers)

    call_args = mock_firestore["create_session"].call_args
    assert call_args is not None
    assert "UniqueChildName" not in str(call_args)


def test_transcript_not_logged(client, auth_headers, valid_payload, mock_story_agent, mock_firestore, caplog):
    """transcript content must not appear anywhere in server log output."""
    valid_payload["transcript"] = "SensitiveTranscriptXYZ"

    with caplog.at_level(logging.INFO, logger="app.routers.story"):
        client.post("/story/generate", json=valid_payload, headers=auth_headers)

    assert "SensitiveTranscriptXYZ" not in caplog.text


def test_child_name_not_logged(client, auth_headers, valid_payload, mock_story_agent, mock_firestore, caplog):
    """child_name must not appear anywhere in server log output."""
    valid_payload["child_name"] = "UniqueChildNameLogging"

    with caplog.at_level(logging.INFO, logger="app.routers.story"):
        client.post("/story/generate", json=valid_payload, headers=auth_headers)

    assert "UniqueChildNameLogging" not in caplog.text


def test_session_id_truncated_in_logs(client, auth_headers, valid_payload, mock_story_agent, mock_firestore, caplog):
    """Only the first 8 chars of session_id are logged (pseudonymity)."""
    session_id = "abcdef1234567890-full-session-uuid"
    valid_payload["session_id"] = session_id

    with caplog.at_level(logging.INFO, logger="app.routers.story"):
        client.post("/story/generate", json=valid_payload, headers=auth_headers)

    assert session_id[:8] in caplog.text
    assert session_id not in caplog.text


def test_objects_and_scene_are_stored(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    """objects and scene ARE permitted Firestore fields and must be passed to create_session."""
    client.post("/story/generate", json=valid_payload, headers=auth_headers)

    call_args = mock_firestore["create_session"].call_args
    assert call_args is not None
    positional = call_args[0]   # (session_id, child_age, objects, scene)
    assert positional[2] == valid_payload["objects"]
    assert positional[3] == valid_payload["scene"]
