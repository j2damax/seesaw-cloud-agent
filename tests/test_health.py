"""GET /health — unauthenticated health probe."""


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_health_returns_correct_body(client):
    r = client.get("/health")
    assert r.json() == {"status": "ok", "version": "1.0.0"}


def test_health_requires_no_auth(client):
    """Health endpoint must be reachable without an API key (Cloud Run probe)."""
    r = client.get("/health")  # no X-SeeSaw-Key header
    assert r.status_code == 200
