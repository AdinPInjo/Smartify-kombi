from smartify.db.migrations import load_migrations


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["hardware"] == "mock"
    assert body["schema_version"] == len(load_migrations())
