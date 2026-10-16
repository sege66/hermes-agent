"""Desktop live-update bridge (ki66 local feature).

The always-on gateway owns state.db; the desktop app renders from a separate
process. Without a nudge, a Telegram turn lands in SQLite and the open desktop
window shows nothing. gateway/session.py POSTs to the desktop backend's
loopback /internal/session-updated, which re-broadcasts over the desktop WS.

Regression coverage for the 2026-07-28 snapshot-restore incident: the feature
lived only as an uncommitted worktree edit and was silently dropped by an
update. These tests fail if the wiring is lost again.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import gateway.session as gs


class TestExternalSourceGate:
    """Only off-box sessions need the cross-process nudge."""

    @pytest.mark.parametrize("source", ["telegram", "discord", "slack", "Matrix"])
    def test_external_sources_notify(self, source):
        assert gs._is_external_session_source(source) is True

    @pytest.mark.parametrize("source", ["", "cli", "tui", "CLI", None, "local", "desktop"])
    def test_local_sources_do_not_notify(self, source):
        assert gs._is_external_session_source(source) is False


class TestEventUrls:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv(
            "HERMES_DESKTOP_SESSION_EVENT_URL", "http://127.0.0.1:9999/x"
        )
        assert gs._desktop_session_event_urls() == ["http://127.0.0.1:9999/x"]

    def test_falls_back_to_port_scan(self, monkeypatch):
        monkeypatch.delenv("HERMES_DESKTOP_SESSION_EVENT_URL", raising=False)
        monkeypatch.setattr(gs, "_desktop_ready_ports_from_log", lambda: [])
        urls = gs._desktop_session_event_urls()
        assert urls, "expected candidate ports"
        assert all(u.endswith("/internal/session-updated") for u in urls)
        assert len(urls) == len(set(urls)), "duplicate ports in candidate list"

    def test_logged_ready_port_is_tried_first(self, monkeypatch):
        monkeypatch.delenv("HERMES_DESKTOP_SESSION_EVENT_URL", raising=False)
        monkeypatch.setattr(gs, "_desktop_ready_ports_from_log", lambda: [9127])
        assert gs._desktop_session_event_urls()[0] == (
            "http://127.0.0.1:9127/internal/session-updated"
        )

    def test_ready_port_parsed_from_log(self, monkeypatch, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "desktop.log").write_bytes(
            b"noise\nHERMES_BACKEND_READY port=9123\nmore\n"
            b"HERMES_DASHBOARD_READY port=9124\n"
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        # newest-first
        assert gs._desktop_ready_ports_from_log()[0] == 9124

    def test_missing_log_is_not_fatal(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        assert gs._desktop_ready_ports_from_log() == []


class TestNotifyDelivery:
    """The POST actually reaches a listener and carries the right body."""

    def test_posts_payload_to_desktop(self, monkeypatch):
        received = []
        done = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                received.append((self.path, json.loads(self.rfile.read(n))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
                done.set()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            monkeypatch.setenv(
                "HERMES_DESKTOP_SESSION_EVENT_URL",
                f"http://127.0.0.1:{port}/internal/session-updated",
            )
            gs._notify_desktop_session_updated("sess-1", "assistant", "sess-0")
            assert done.wait(3.0), "desktop never received the notify POST"
        finally:
            srv.shutdown()

        path, body = received[0]
        assert path == "/internal/session-updated"
        assert body == {
            "session_id": "sess-1",
            "role": "assistant",
            "previous_session_id": "sess-0",
        }

    def test_notifies_every_announced_backend(self, monkeypatch):
        # ki66: one backend per desktop profile (primary + e.g. "atlas"), and
        # the renderer only refreshes from the ACTIVE profile's socket — so a
        # notify that stops at the first 2xx (the newest-announced backend)
        # silently starves the primary. Every announced port must be hit.
        received = []
        events = []

        def _serve():
            done = threading.Event()

            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    n = int(self.headers.get("Content-Length", 0))
                    received.append((self.server.server_address[1], json.loads(self.rfile.read(n))))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"{}")
                    done.set()

                def log_message(self, *a):
                    pass

            srv = HTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            events.append(done)
            return srv

        primary, atlas = _serve(), _serve()
        try:
            monkeypatch.delenv("HERMES_DESKTOP_SESSION_EVENT_URL", raising=False)
            # Newest first, as _desktop_ready_ports_from_log reports them.
            monkeypatch.setattr(
                gs,
                "_desktop_ready_ports_from_log",
                lambda: [atlas.server_address[1], primary.server_address[1]],
            )
            gs._notify_desktop_session_updated("sess-1", "assistant")
            assert all(e.wait(3.0) for e in events), "an announced backend was skipped"
        finally:
            primary.shutdown()
            atlas.shutdown()

        assert sorted(port for port, _ in received) == sorted(
            [primary.server_address[1], atlas.server_address[1]]
        )
        assert all(body["session_id"] == "sess-1" for _, body in received)

    def test_empty_session_id_is_a_noop(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            gs, "_desktop_session_event_urls", lambda: called.append(1) or []
        )
        gs._notify_desktop_session_updated("")
        assert not called

    def test_unreachable_desktop_never_raises(self, monkeypatch):
        # Closed port — the notify must swallow it; a dead desktop must never
        # break a transcript write.
        monkeypatch.setenv(
            "HERMES_DESKTOP_SESSION_EVENT_URL", "http://127.0.0.1:1/internal/x"
        )
        gs._notify_desktop_session_updated("sess-1", "user")
        for t in threading.enumerate():
            if t.name == "hermes-desktop-session-notify":
                t.join(3.0)
                assert not t.is_alive()


class TestChokePointWiring:
    """append_to_transcript is the single hook site — verify both branches."""

    def _store(self, source):
        store = object.__new__(gs.SessionStore)

        class _DB:
            def get_session(self, sid):
                return {"source": source}

        store._db = _DB()
        return store

    def test_skip_db_still_notifies(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            gs, "_notify_desktop_session_updated", lambda *a, **k: seen.append(a)
        )
        store = self._store("telegram")
        store.append_to_transcript("s1", {"role": "user"}, skip_db=True)
        assert seen == [("s1", "user")], "skip_db path lost the desktop nudge"

    def test_local_source_is_not_notified(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            gs, "_notify_desktop_session_updated", lambda *a, **k: seen.append(a)
        )
        store = self._store("cli")
        store.append_to_transcript("s1", {"role": "user"}, skip_db=True)
        assert seen == []

    def test_no_db_is_a_noop(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            gs, "_notify_desktop_session_updated", lambda *a, **k: seen.append(a)
        )
        store = object.__new__(gs.SessionStore)
        store._db = None
        store.append_to_transcript("s1", {"role": "user"}, skip_db=True)
        assert seen == []

    def test_db_lookup_failure_does_not_propagate(self):
        class _DB:
            def get_session(self, sid):
                raise RuntimeError("db down")

        store = object.__new__(gs.SessionStore)
        store._db = _DB()
        # Must not raise — a broken DB lookup cannot break a transcript write.
        store.append_to_transcript("s1", {"role": "user"}, skip_db=True)


class TestRotationNotify:
    """Session rotations carry the predecessor id so the desktop can follow.

    ki66: the /new slash handler already reported (new, previous); the idle /
    daily auto-reset in get_or_create_session — the common case — did not, so
    the desktop stayed pinned to the ended session (2026-08-24 live probe).
    """

    def _store(self, tmp_path):
        from datetime import datetime, timedelta
        from gateway.config import GatewayConfig, Platform
        from gateway.session import SessionSource

        config = GatewayConfig()
        store = gs.SessionStore(sessions_dir=tmp_path, config=config)
        source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", user_id="u1")
        return store, source, datetime, timedelta

    def test_idle_time_does_not_rotate_or_notify(self, tmp_path, monkeypatch):
        """Upstream routing never rotates on time (``_route_reset_reason``).

        Desktop follow is only for explicit /new — see
        ``test_explicit_reset_notifies_unless_suppressed``.
        """
        store, source, datetime, timedelta = self._store(tmp_path)
        calls = []
        monkeypatch.setattr(
            gs, "_notify_desktop_session_updated",
            lambda sid, role=None, previous_session_id=None: calls.append((sid, previous_session_id)),
        )
        first = store.get_or_create_session(source)
        assert calls == [], "a fresh session has no predecessor to follow"
        first.updated_at = datetime.now() - timedelta(minutes=5)
        store._save()

        again = store.get_or_create_session(source, touch_activity=False)

        assert again.session_id == first.session_id
        assert again.was_auto_reset is not True
        assert calls == []

    def test_explicit_reset_notifies_unless_suppressed(self, tmp_path, monkeypatch):
        store, source, _, _ = self._store(tmp_path)
        calls = []
        monkeypatch.setattr(
            gs, "_notify_desktop_session_updated",
            lambda sid, role=None, previous_session_id=None: calls.append((sid, previous_session_id)),
        )
        first = store.get_or_create_session(source)

        second = store.reset_session(first.session_key)
        assert second is not None and second.session_id != first.session_id
        assert calls == [(second.session_id, first.session_id)]

        # The /new handler nudges itself after rebinding a topic lane.
        third = store.reset_session(first.session_key, notify_desktop=False)
        assert third is not None and third.session_id != second.session_id
        assert calls == [(second.session_id, first.session_id)]

    def test_local_platform_rotation_is_silent(self, tmp_path, monkeypatch):
        """LOCAL resets route to the authority-fenced recovery path (no desktop notify).

        Upstream 8b8559bf58 moved LOCAL resets into
        ``gateway.session_local_recovery.reset_local_session``, which carries no desktop
        mirror call and needs a served authority's epoch — a bare SessionStore can no
        longer perform the reset itself. Pin the routing (and the silence it implies)
        so a regression to the notifying ``_replace_route`` path is caught.
        """
        from gateway import session_local_recovery
        from gateway.config import Platform
        from gateway.session import SessionSource

        store, _, datetime, timedelta = self._store(tmp_path)
        calls = []
        routed = []
        monkeypatch.setattr(
            gs, "_notify_desktop_session_updated",
            lambda *a, **k: calls.append((a, k)),
        )
        monkeypatch.setattr(
            session_local_recovery, "reset_local_session",
            lambda store_, old, sid, now, dn: routed.append(old.session_key),
        )
        local = SessionSource(platform=Platform.LOCAL, chat_id="cli", user_id="me")
        first = store.get_or_create_session(local)
        first.updated_at = datetime.now() - timedelta(minutes=5)
        store._save()
        store.get_or_create_session(local, touch_activity=False)
        store.reset_session(first.session_key)

        assert routed == [first.session_key]
        assert calls == []
