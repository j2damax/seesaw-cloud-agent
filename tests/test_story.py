"""POST /story/generate — validation, generation, multi-turn, and final-beat logic."""


# ── Validation tests ──────────────────────────────────────────────────────────

def test_missing_objects_returns_422(client, auth_headers):
    r = client.post(
        "/story/generate",
        json={"scene": ["living_room"], "child_age": 5, "child_name": "Vihas"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_missing_child_age_returns_422(client, auth_headers):
    r = client.post(
        "/story/generate",
        json={"objects": ["teddy_bear"], "scene": ["living_room"], "child_name": "Vihas"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_missing_child_name_returns_422(client, auth_headers):
    r = client.post(
        "/story/generate",
        json={"objects": ["teddy_bear"], "scene": ["living_room"], "child_age": 5},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_child_age_too_low_returns_422(client, auth_headers):
    r = client.post(
        "/story/generate",
        json={"objects": ["teddy_bear"], "scene": ["living_room"], "child_age": 1, "child_name": "Vihas"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_child_age_too_high_returns_422(client, auth_headers):
    r = client.post(
        "/story/generate",
        json={"objects": ["teddy_bear"], "scene": ["living_room"], "child_age": 13, "child_name": "Vihas"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_empty_child_name_returns_422(client, auth_headers):
    r = client.post(
        "/story/generate",
        json={"objects": ["teddy_bear"], "scene": ["living_room"], "child_age": 5, "child_name": ""},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ── Generation tests ──────────────────────────────────────────────────────────

def test_valid_payload_returns_200(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    assert r.status_code == 200


def test_response_has_all_required_fields(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    body = r.json()
    assert "story_text" in body
    assert "question" in body
    assert "is_ending" in body
    assert "session_id" in body
    assert "beat_index" in body


def test_first_beat_index_is_zero(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    mock_firestore["get_beat_count"].return_value = 0
    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    assert r.json()["beat_index"] == 0


def test_session_id_generated_when_omitted(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    session_id = r.json()["session_id"]
    assert isinstance(session_id, str) and len(session_id) > 0


def test_session_id_echoed_when_provided(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    valid_payload["session_id"] = "my-custom-session-id"
    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    assert r.json()["session_id"] == "my-custom-session-id"


def test_second_beat_increments_beat_index(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    mock_firestore["get_beat_count"].return_value = 1
    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    assert r.json()["beat_index"] == 1


def test_final_beat_forces_is_ending_true(client, auth_headers, valid_payload, mock_story_agent, mock_firestore):
    """When beat_index reaches MAX_TURNS-1 (7), agent must be called with is_final_beat=True
    and the response must have is_ending=True."""
    mock_firestore["get_beat_count"].return_value = 7  # MAX_TURNS - 1
    mock_story_agent.return_value = {
        "story_text": "And they all lived happily ever after.",
        "question": "Was that a good adventure?",
        "is_ending": True,
    }

    r = client.post("/story/generate", json=valid_payload, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["is_ending"] is True

    # Verify the router correctly signalled the final beat to the agent
    _, kwargs = mock_story_agent.call_args
    assert kwargs["is_final_beat"] is True
