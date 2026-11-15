"""ki66 (local fork) tui_gateway additions, kept out of upstream ``server.py``.

``tests/tui_gateway/contracts/test_generated.py`` scans ``tui_gateway/*.py`` for
``_broadcast_global_event("<event>"`` literals, so the emit for the local
``session.external_updated`` contract event lives here with the literal name.
"""

from __future__ import annotations


def broadcast_session_external_updated(payload: dict | None = None) -> None:
    """An off-box turn landed in state.db; nudge every desktop WS to refetch.

    The gateway process POSTs to the desktop backend
    (``hermes_cli/web_server_ki66.py``), which calls this.
    """
    from tui_gateway.server import _broadcast_global_event

    _broadcast_global_event("session.external_updated", payload)
