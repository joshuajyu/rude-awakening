import threading

import pytest
from fastapi.testclient import TestClient

from server.app import create_app, summarize
from server.config import Settings

TOKEN = "test-token-0123456789abcdef"
AUTH = {"X-Webhook-Token": TOKEN}


class FakeRinger:
    def __init__(self):
        self.calls = []

    def ring(self, volume, duration, stop: threading.Event):
        self.calls.append((volume, duration))
        stop.wait(5)

    def check(self):
        return True


@pytest.fixture
def ringer():
    return FakeRinger()


@pytest.fixture
def client(ringer):
    settings = Settings(webhook_token=TOKEN, nest_ip="10.0.0.50")
    with TestClient(create_app(settings, ringer=ringer, serve_media=False)) as c:
        yield c


def test_health_needs_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "alarm_active": False}


def test_health_can_check_nest(client):
    assert client.get("/health?nest=true").json()["nest_reachable"] is True


@pytest.mark.parametrize("path", ["/page", "/stop", "/test"])
@pytest.mark.parametrize("headers", [{}, {"X-Webhook-Token": "wrong"}, {"X-Webhook-Token": ""}])
def test_endpoints_reject_bad_tokens(client, ringer, path, headers):
    r = client.post(path, headers=headers, json={})
    assert r.status_code == 401
    assert ringer.calls == []


def test_page_rings_at_alarm_volume(client, ringer):
    r = client.post("/page", headers=AUTH, json={"alert": {"summary": "API down"}})
    assert r.status_code == 202
    assert r.json() == {"status": "ringing"}
    assert ringer.calls == [(90, 600)]
    assert client.get("/health").json()["alarm_active"] is True


def test_duplicate_page_is_ignored(client, ringer):
    client.post("/page", headers=AUTH, json={})
    r = client.post("/page", headers=AUTH, json={})
    assert r.json() == {"status": "already_ringing"}
    assert len(ringer.calls) == 1


def test_page_accepts_any_body(client, ringer):
    assert client.post("/page", headers=AUTH, content=b"not json").status_code == 202
    assert ringer.calls == [(90, 600)]


def test_stop(client):
    assert client.post("/stop", headers=AUTH).json() == {"status": "idle"}
    client.post("/page", headers=AUTH)
    assert client.post("/stop", headers=AUTH).json() == {"status": "stopped"}
    assert client.get("/health").json()["alarm_active"] is False


def test_test_uses_test_volume_and_duration(client, ringer):
    assert client.post("/test", headers=AUTH).json() == {"status": "testing"}
    assert ringer.calls == [(40, 15)]


def test_page_takes_over_from_test(client, ringer):
    client.post("/test", headers=AUTH)
    assert client.post("/page", headers=AUTH).json() == {"status": "ringing"}
    assert ringer.calls == [(40, 15), (90, 600)]


def test_no_public_docs(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("body, expected", [
    (b"", "empty body"),
    (b"<xml/>", "non-JSON body (6 bytes)"),
    (b"[1, 2]", "JSON list"),
    (b'{"a": 1, "b": 2}', "keys=[a, b]"),
    (b'{"event": "x", "data": {"incident": {"title": "DB down"}}}', "keys=[event, data] title='DB down'"),
])
def test_summarize(body, expected):
    assert summarize(body) == expected
