"""Connecting to the remote dashboard from the van's dashboard."""

from __future__ import annotations

import base64
import json

import pytest

from smartify.errors import InvalidInput
from smartify.services.cloud_link import parse_code
from smartify.services.cloud_sync import CloudError


def make_code(url: str, token: str) -> str:
    raw = json.dumps({"u": url, "t": token}).encode()
    return "SMK1-" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


class FakeCloud:
    def __init__(self, instance: str = "abc123") -> None:
        self.calls: list[tuple[str, dict, str]] = []
        self.error: str | None = None
        self.instance = instance
        self.commands: list[dict] = []

    def __call__(self, url, body, token):
        if self.error:
            raise CloudError(self.error)
        self.calls.append((url, body, token))
        return {"commands": self.commands, "accepted": {}, "instance": self.instance}


def test_parse_code():
    assert parse_code(" " + make_code("https://example.com/kombi/", "tok") + "\n") == (
        "https://example.com/kombi",
        "tok",
    )
    for bad in ("hello", "SMK1-%%%", make_code("ftp://x", "t"), make_code("https://x", "")):
        with pytest.raises(InvalidInput):
            parse_code(bad)


@pytest.fixture
def cloud(ctx):
    fake = FakeCloud()
    ctx.cloud_transport = fake
    return fake


def test_connect_with_a_code(client, ctx, cloud):
    assert client.get("/api/cloud").json() == {
        "connected": False,
        "source": None,
        "url": None,
        "status": None,
    }
    response = client.post(
        "/api/cloud", json={"code": make_code("https://van.example/kombi", "t0k")}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["connected"] and data["source"] == "dashboard"
    assert data["url"] == "https://van.example/kombi"
    assert data["status"]["last_ok_at"] is not None
    url, body, token = cloud.calls[0]
    assert url == "https://van.example/kombi/api/device/sync" and token == "t0k"
    assert "state" in body and "history" in body  # the first exchange sends everything

    assert client.delete("/api/cloud").json()["connected"] is False


def test_a_wrong_code_is_explained_and_not_saved(client, ctx, cloud):
    cloud.error = "HTTP 401: invalid device token"
    response = client.post("/api/cloud", json={"code": make_code("https://van.example", "old")})
    assert response.status_code == 422 and "newer one" in response.json()["detail"]
    cloud.error = "cloud unreachable: [Errno -2] Name or service not known"
    response = client.post("/api/cloud", json={"code": make_code("https://nope.example", "x")})
    assert "cannot reach nope.example" in response.json()["detail"]
    assert client.get("/api/cloud").json()["connected"] is False
    assert client.post("/api/cloud", json={"code": "not a code"}).status_code == 422


def test_a_reinstalled_cloud_gets_everything_again(client, ctx, cloud):
    code = make_code("https://van.example", "t")
    client.post("/api/cloud", json={"code": code})
    sync = ctx.cloud
    sync._set_cursor("last_command_id", 41)  # commands seen from this cloud
    sync._set_cursor("history:sensor_samples", 900)

    cloud.instance = "fresh-install"  # same address, new installation: ids start at 1 again
    cloud.commands = [{"id": 1, "type": "relay_auto", "target": "x", "payload": {}}]
    sync.tick()
    assert sync._cursor("last_command_id") == 0  # reset, command 1 not skipped later
    assert sync._cursor("history:sensor_samples") == 0
    sync.tick()
    assert cloud.calls[-1][1]["last_command_id"] == 0


def test_a_failed_switch_keeps_the_working_connection(client, ctx, cloud):
    client.post("/api/cloud", json={"code": make_code("https://van.example", "good")})
    ctx.cloud._set_cursor("last_command_id", 7)
    cloud.error = "cloud unreachable: timed out"
    response = client.post("/api/cloud", json={"code": make_code("https://other.example", "x")})
    assert response.status_code == 422
    view = client.get("/api/cloud").json()
    assert view["url"] == "https://van.example"  # still connected to the old one
    assert ctx.cloud._cursor("last_command_id") == 7  # and nothing was reset
