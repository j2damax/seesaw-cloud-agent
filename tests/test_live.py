"""
Live smoke tests against the deployed Cloud Run service.

These tests hit the real endpoint and require:
  - SEESAW_API_KEY env var set to the production key
  - SEESAW_LIVE_TEST=1 env var (or --live pytest flag) to opt in

Run with:
    SEESAW_API_KEY=<key> SEESAW_LIVE_TEST=1 pytest tests/test_live.py -v -m live
"""
import os
import uuid
import pytest
import httpx

LIVE_BASE_URL = "https://seesaw-cloud-agent-531853173205.europe-west1.run.app"
LIVE_ENABLED  = os.environ.get("SEESAW_LIVE_TEST", "0") == "1"
LIVE_API_KEY  = os.environ.get("SEESAW_API_KEY", "")

pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def require_live():
    if not LIVE_ENABLED:
        pytest.skip("Set SEESAW_LIVE_TEST=1 to run live tests")
    if not LIVE_API_KEY:
        pytest.skip("Set SEESAW_API_KEY to run live tests")


@pytest.fixture(scope="module")
def live_headers():
    return {"X-SeeSaw-Key": LIVE_API_KEY}


def test_live_health():
    r = httpx.get(f"{LIVE_BASE_URL}/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_live_auth_rejection(live_headers):
    r = httpx.post(
        f"{LIVE_BASE_URL}/story/generate",
        json={"objects": ["teddy_bear"], "scene": ["living_room"], "child_age": 5, "child_name": "Test"},
        headers={"X-SeeSaw-Key": "wrong-key"},
        timeout=10,
    )
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized"}


def test_live_story_generate(live_headers):
    r = httpx.post(
        f"{LIVE_BASE_URL}/story/generate",
        json={
            "objects": ["teddy_bear", "book"],
            "scene":   ["living_room"],
            "child_age":  5,
            "child_name": "Vihas",
        },
        headers=live_headers,
        timeout=60,  # allow for cold-start (~35s)
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["story_text"]) > 0
    assert len(body["question"]) > 0
    assert body["beat_index"] == 0
    assert isinstance(body["is_ending"], bool)
    assert isinstance(body["session_id"], str)


def test_live_model_latest(live_headers):
    r = httpx.get(f"{LIVE_BASE_URL}/model/latest", headers=live_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["size_bytes"] == 1_077_509_216
    assert "q8_0" in body["download_url"]
    assert body["model_version"] == "1.0.2"


def test_live_unknown_session_returns_404(live_headers):
    non_existent_id = str(uuid.uuid4())
    r = httpx.get(f"{LIVE_BASE_URL}/session/{non_existent_id}", headers=live_headers, timeout=10)
    assert r.status_code == 404
