"""ki66 local: desktop live-update bridge for the gateway session store.

Local-only module (upstream never touches it). ``gateway/session.py`` and
``gateway/session_transcript.py`` keep one import line plus call lines; all the
logic lives here. Imports nothing from ``gateway`` so it can never be part of
an import cycle.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Log-record parity with the origin module.
logger = logging.getLogger("gateway.session")

# ── Desktop live-update bridge (ki66 local feature) ──────────────────────
# The always-on gateway owns state.db, but the desktop app renders from its own
# process. Without a nudge, a turn that arrives on Telegram lands in the DB and
# the open desktop window shows nothing until the user reloads. POST to the
# desktop backend's loopback ``/internal/session-updated``, which re-broadcasts
# ``session.external_updated`` over its WS so the UI refetches.
#
# ponytail: fire-and-forget on a daemon thread with a ~120ms timeout — a
# missed refresh nudge is cosmetic, a blocked transcript write is not.
_DESKTOP_SESSION_EVENT_PORTS = (*range(9120, 9131), 9119)
_DESKTOP_SESSION_EVENT_TIMEOUT_S = 0.12
_DESKTOP_READY_RE = re.compile(rb"HERMES_(?:DASHBOARD|BACKEND)_READY port=(\d+)")
_LOCAL_SOURCES = frozenset({"", "cli", "tui", "local", "desktop"})


def _is_external_session_source(source: Any) -> bool:
    """True when a session originated off-box (telegram, discord, …).

    Desktop- and CLI-originated turns already paint in their own process; only
    external sources need the cross-process refresh nudge.
    """
    return str(source or "").strip().lower() not in _LOCAL_SOURCES


def _desktop_ready_ports_from_log() -> List[int]:
    """Ports the desktop backend most recently announced, newest first."""
    log_path = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "logs" / "desktop.log"
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536), os.SEEK_SET)
            data = fh.read()
    except Exception:
        return []

    ports: List[int] = []
    for match in _DESKTOP_READY_RE.finditer(data):
        try:
            ports.append(int(match.group(1)))
        except ValueError:
            continue
    return list(reversed(ports[-3:]))


def _desktop_session_event_targets() -> "tuple[List[str], set]":
    """Ordered candidate URLs plus the subset that are announced live backends.

    ki66: the desktop runs one ``hermes serve`` backend per profile (the primary
    plus every extra profile, e.g. ``atlas``) and keeps their sockets open
    concurrently, but the renderer's ``session.external_updated`` refresh
    handler only listens on the *active* profile's socket. Every port the
    desktop announced is therefore a live target that must be nudged; the
    static fallback range is only a guess for when the log yielded nothing.
    """
    configured = (os.environ.get("HERMES_DESKTOP_SESSION_EVENT_URL") or "").strip()
    if configured:
        return [configured], {configured}

    announced: List[str] = []
    for port in _desktop_ready_ports_from_log():
        url = f"http://127.0.0.1:{port}/internal/session-updated"
        if url not in announced:
            announced.append(url)

    urls = list(announced)
    for port in _DESKTOP_SESSION_EVENT_PORTS:
        url = f"http://127.0.0.1:{port}/internal/session-updated"
        if url not in urls:
            urls.append(url)

    return urls, set(announced)


def _desktop_session_event_urls() -> List[str]:
    return _desktop_session_event_targets()[0]


def _notify_desktop_session_updated(
    session_id: str,
    role: Any = None,
    previous_session_id: Optional[str] = None,
) -> None:
    if not session_id:
        return

    payload = json.dumps(
        {
            "session_id": session_id,
            "role": role,
            "previous_session_id": previous_session_id,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def _send() -> None:
        urls, announced = _desktop_session_event_targets()
        delivered = False
        for url in urls:
            # Announced ports are all live per-profile backends: notify each
            # of them (a stale one just refuses the connection, cheaply). The
            # static fallback range is walked only until the first success,
            # and not at all once an announced backend already took it.
            if delivered and url not in announced:
                return
            request = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=_DESKTOP_SESSION_EVENT_TIMEOUT_S,
                ):
                    delivered = True
            except Exception:
                continue

    threading.Thread(
        target=_send,
        name="hermes-desktop-session-notify",
        daemon=True,
    ).start()


def _notify_desktop_rotation(platform_value: Any, new_session_id: str, previous_session_id: str) -> None:
    """Tell the desktop that an external chat rotated to a fresh session."""
    try:
        if not _is_external_session_source(platform_value):
            return
        _notify_desktop_session_updated(new_session_id, previous_session_id=previous_session_id)
    except Exception as exc:
        logger.debug("Desktop rotation notification failed: %s", exc)


def _notify_route_rotation(source: Any, decision: Any, create_kwargs: Any) -> None:
    """Hook for ``SessionStore`` route creation: follow a rotated external chat."""
    if decision.prev_session_id and create_kwargs:
        _notify_desktop_rotation(
            getattr(getattr(source, "platform", None), "value", None),
            create_kwargs.get("session_id") or decision.entry.session_id,
            decision.prev_session_id,
        )


def _notify_reset_rotation(notify_desktop: bool, old_entry: Any, new_entry: Any) -> None:
    """Hook for ``SessionStore.reset_session``: follow an explicit reset."""
    if notify_desktop and new_entry is not None and old_entry.session_id:
        _notify_desktop_rotation(
            getattr(old_entry.platform, "value", None),
            new_entry.session_id,
            old_entry.session_id,
        )


def _notify_desktop_if_external(store: Any, session_id: str, message: Dict[str, Any]) -> None:
    """Nudge the desktop app to refetch when an off-box turn lands.

    ki66: hooked at this single choke point (``append_to_transcript``) rather
    than at each DB write site. Every transcript append funnels through it.
    ``store`` is the ``SessionStore`` (``SessionTranscriptMixin`` self).
    """
    try:
        try:
            db = store._db_for_session_id(session_id) or getattr(store, "_db", None)
        except Exception:
            db = getattr(store, "_db", None)
        if not db:
            return
        session = db.get_session(session_id) or {}
        if _is_external_session_source(session.get("source")):
            _notify_desktop_session_updated(session_id, message.get("role"))
    except Exception as exc:
        logger.debug("Desktop session update notification failed: %s", exc)
