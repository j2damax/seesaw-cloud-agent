"""
Shared fixtures for the seesaw-cloud-agent test suite.

Environment variables are set at module load time so that Pydantic Settings
picks them up (env vars take priority over .env file).
"""
import os

# Set test env vars BEFORE importing the app — Settings() is instantiated at
# import time, and env vars take priority over the .env file.
os.environ["SEESAW_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test"
os.environ["FIRESTORE_PROJECT"] = "test-project"
os.environ["GCS_BUCKET_NAME"] = "test-bucket"

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

TEST_API_KEY = "test-key"

MOCK_BEAT = {
    "story_text": "You find a magical bear in the corner.",
    "question": "What do you think the bear wants to do?",
    "is_ending": False,
}

MOCK_SESSION = {
    "session_id": "test-session-00000000",
    "child_age": 5,
    "objects": ["teddy_bear", "book"],
    "beat_count": 1,
    "created_at": None,
    "beats": [MOCK_BEAT],
}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"X-SeeSaw-Key": TEST_API_KEY}


@pytest.fixture
def valid_payload():
    return {
        "objects": ["teddy_bear", "book"],
        "scene": ["living_room"],
        "child_age": 5,
        "child_name": "Vihas",
    }


@pytest.fixture
def mock_story_agent():
    """Patches generate_story_beat in the story router's namespace."""
    with patch("app.routers.story.generate_story_beat", new_callable=AsyncMock) as mock:
        mock.return_value = MOCK_BEAT.copy()
        yield mock


@pytest.fixture
def mock_firestore():
    """
    Patches all Firestore calls in story.py and session.py.
    Returns a dict of mocks for per-test assertions.
    """
    with (
        patch("app.routers.story.create_session", new_callable=AsyncMock) as mock_create,
        patch("app.routers.story.append_beat", new_callable=AsyncMock) as mock_append,
        patch("app.routers.story.get_beat_count", new_callable=AsyncMock) as mock_count,
        patch("app.routers.session.get_session", new_callable=AsyncMock) as mock_get,
        patch("app.routers.session.delete_session", new_callable=AsyncMock) as mock_delete,
    ):
        mock_count.return_value = 0
        mock_get.return_value = MOCK_SESSION.copy()
        yield {
            "create_session": mock_create,
            "append_beat": mock_append,
            "get_beat_count": mock_count,
            "get_session": mock_get,
            "delete_session": mock_delete,
        }


@pytest.fixture
def mock_model_cdn():
    """Patches GCS signed URL generation in the model router."""
    with patch("app.routers.model.get_signed_model_url", new_callable=AsyncMock) as mock:
        mock.return_value = "https://fake-signed-url.example.com/seesaw-gemma3-1b-q8_0.gguf"
        yield mock
