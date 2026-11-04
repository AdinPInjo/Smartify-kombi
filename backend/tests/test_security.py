"""Fixes from the security review (0.11.0): each test plays the attack or failure."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from smartify.errors import InvalidInput
from smartify.services.cloud_link import check_url
from smartify.services.cloud_sync import CloudError, apply_command, http_transport


def relay(ctx, name="heater"):
    return next(r for r in ctx.relays.list() if r.name == name)


# --- remote commands get the van's own checks ------------------------------------------------


def test_remote_relay_update_is_validated(ctx):
    heater = relay(ctx)
    bad = {"type": "relay_update", "target": heater.id, "payload": {"min_on_seconds": "soon"}}
    with pytest.raises(InvalidInput):
        apply_command(ctx, bad)
    assert relay(ctx).min_on_seconds == heater.min_on_seconds  # nothing stored


def test_remote_cannot_rewire_a_relay(ctx):
    heater = relay(ctx)
    for change in ({"gpio_pin": 5}, {"active_low": True}):
        with pytest.raises(InvalidInput, match="at the van"):
            apply_command(ctx, {"type": "relay_update", "target": heater.id, "payload": change})
    assert relay(ctx).gpio_pin == heater.gpio_pin


def test_remote_manual_and_rules_are_validated(ctx):
    heater = relay(ctx)
    with pytest.raises(InvalidInput):
        apply_command(
            ctx, {"type": "relay_manual", "target": heater.id, "payload": {"state": "maybe"}}
        )
    with pytest.raises(InvalidInput):
        apply_command(
            ctx,
            {
                "type": "rule_create",
                "target": heater.id,
                "payload": {"name": "x", "condition": {}, "action": "on", "cooldown_seconds": "x"},
            },
        )
    with pytest.raises(InvalidInput):
        apply_command(
            ctx, {"type": "relay_update", "target": heater.id, "payload": ["not", "a", "dict"]}
        )


def test_valid_remote_changes_still_work(ctx):
    heater = relay(ctx)
    apply_command(
        ctx,
        {
            "type": "relay_update",
            "target": heater.id,
            "payload": {"label": "Diesel", "min_on_seconds": 120},
        },
    )
    assert relay(ctx).label == "Diesel" and relay(ctx).min_on_seconds == 120
    apply_command(
        ctx,
        {
            "type": "relay_manual",
            "target": heater.id,
            "payload": {"state": "on", "duration_minutes": 30},
        },
    )
    assert relay(ctx).manual_state == "on"


# --- the sensor test can't touch a relay's pin -----------------------------------------------


def test_sensor_test_refuses_relay_pins(client, ctx):
    pin = relay(ctx).gpio_pin
    response = client.post("/api/sensors/test", json={"kind": "door", "config": {"pin": pin}})
    assert response.status_code == 409 and "relay" in response.json()["detail"]
    assert (
        client.post("/api/sensors/test", json={"kind": "door", "config": {"pin": 22}}).status_code
        == 200
    )


# --- the remote dashboard link ---------------------------------------------------------------


def test_remote_dashboard_must_use_https():
    assert check_url("https://kombi.example.com/") == "https://kombi.example.com"
    with pytest.raises(InvalidInput, match="https"):
        check_url("http://kombi.example.com")
    # Plain http only for test setups on the local network.
    for local in ("http://127.0.0.1:8097", "http://192.168.1.20/kombi", "http://nas.local"):
        assert check_url(local).startswith("http://")


def _read_body(handler: BaseHTTPRequestHandler) -> None:
    """Read the request before answering, like a real server: closing a connection
    with unread data makes Linux reset it, which the client may see first."""
    handler.rfile.read(int(handler.headers.get("Content-Length") or 0))


class _Server:
    def __init__(self, handler):
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/api/device/sync"

    def close(self):
        self.httpd.shutdown()


def test_sync_refuses_redirects_and_huge_answers():
    seen_tokens = []

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            _read_body(self)
            seen_tokens.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/steal")
            self.end_headers()

        def log_message(self, *args):
            pass

    class Huge(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            _read_body(self)
            body = b"[" + b"0," * 3_000_000 + b"0]"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the van stops reading at its limit: expected

        def log_message(self, *args):
            pass

    server = _Server(Redirect)
    try:
        with pytest.raises(CloudError, match="302"):
            http_transport(server.url, {"protocol": 1}, "secret-token")
        assert seen_tokens == ["Bearer secret-token"]  # sent once, never forwarded
    finally:
        server.close()
    server = _Server(Huge)
    try:
        with pytest.raises(CloudError, match="too much"):
            http_transport(server.url, {"protocol": 1}, "t")
    finally:
        server.close()


# --- a dead cut-off sensor switches its relay off -----------------------------------------------


def test_cutoff_with_a_dead_sensor_switches_off(client, ctx):
    heater = relay(ctx)
    client.patch(f"/api/relays/{heater.id}", json={"cutoff_sensor": "inside", "cutoff_max_c": 30})
    client.post(f"/api/relays/{heater.id}/manual", json={"state": "on"})
    assert relay(ctx).state == "on"
    inside = next(s for s in client.get("/api/sensors").json()["sensors"] if s["name"] == "inside")
    client.delete(f"/api/sensors/{inside['id']}")  # the protecting sensor is gone
    ctx.relays.reconcile(heater.id)
    after = relay(ctx)
    assert after.state == "off" and "no reading from inside" in (after.reason or "")


# --- other websites can't send changes -----------------------------------------------------------


def test_cross_site_changes_are_refused(client, ctx):
    heater = relay(ctx)
    url = f"/api/relays/{heater.id}/manual"
    evil = client.post(url, json={"state": "on"}, headers={"Origin": "http://evil.example"})
    assert evil.status_code == 403
    sneaky = client.post(url, json={"state": "on"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert sneaky.status_code == 403
    own = client.post(
        url,
        json={"state": "on"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert own.status_code == 200
    assert client.get("/api/relays").status_code == 200  # reading is unaffected
