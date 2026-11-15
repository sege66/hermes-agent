"""ki66: the gateway → desktop "external session updated" bridge stays mounted.

``hermes_cli/web_server.py`` keeps one ``include_router`` line for
``hermes_cli/web_server_ki66.router``; the route re-broadcasts over the desktop
WS through ``tui_gateway/server_ki66.broadcast_session_external_updated``.
"""

import pytest


@pytest.fixture
def client(_isolate_hermes_home):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")
    from hermes_cli import web_server

    return TestClient(web_server.app)


@pytest.fixture
def sent(monkeypatch):
    from tui_gateway import server

    calls = []
    monkeypatch.setattr(server, "_broadcast_global_event", lambda event, payload: calls.append((event, payload)))
    return calls


def test_loopback_post_broadcasts_external_update(client, sent, monkeypatch):
    from hermes_cli import web_server

    monkeypatch.setattr(web_server, "_LOOPBACK_HOST_VALUES", frozenset({"testclient"}))
    resp = client.post("/internal/session-updated", json={"session_id": " s1 ", "role": "assistant"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}
    assert sent == [("session.external_updated",
                     {"stored_session_id": "s1", "role": "assistant", "previous_session_id": None})]


def test_non_loopback_post_is_forbidden(client, sent):
    resp = client.post("/internal/session-updated", json={"session_id": "s1"})
    assert resp.status_code == 403
    assert sent == []


def test_blank_session_id_is_rejected(client, sent, monkeypatch):
    from hermes_cli import web_server

    monkeypatch.setattr(web_server, "_LOOPBACK_HOST_VALUES", frozenset({"testclient"}))
    resp = client.post("/internal/session-updated", json={"session_id": "  "})
    assert resp.status_code == 400
    assert sent == []
