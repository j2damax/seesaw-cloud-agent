"""GET /model/latest — response shape, model version, exact size_bytes, expiry format."""
from datetime import datetime


def test_model_latest_returns_200(client, auth_headers, mock_model_cdn):
    r = client.get("/model/latest", headers=auth_headers)
    assert r.status_code == 200


def test_model_response_has_all_required_fields(client, auth_headers, mock_model_cdn):
    r = client.get("/model/latest", headers=auth_headers)
    body = r.json()
    assert "download_url" in body
    assert "model_version" in body
    assert "size_bytes" in body
    assert "expires_at" in body


def test_model_version_is_current(client, auth_headers, mock_model_cdn):
    """model_version must match the constant in model.py after the Q8_0 re-export."""
    r = client.get("/model/latest", headers=auth_headers)
    assert r.json()["model_version"] == "1.0.2"


def test_size_bytes_matches_measured_q8_0_file(client, auth_headers, mock_model_cdn):
    """size_bytes must equal the measured GCS object size from the Colab export."""
    r = client.get("/model/latest", headers=auth_headers)
    assert r.json()["size_bytes"] == 1_077_509_216


def test_expires_at_is_valid_iso8601_utc(client, auth_headers, mock_model_cdn):
    """expires_at must be parseable as an ISO 8601 UTC timestamp."""
    r = client.get("/model/latest", headers=auth_headers)
    expires_at = r.json()["expires_at"]
    # Should not raise
    dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    assert dt.tzinfo is not None
