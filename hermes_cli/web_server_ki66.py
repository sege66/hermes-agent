"""ki66 (local fork) dashboard-backend additions, kept out of ``web_server.py``.

``hermes_cli/web_server.py`` is upstream-owned; it keeps a single
``app.include_router(...web_server_ki66...router)`` line so upstream releases
merge cleanly. The route (``@router.post("/internal/session-updated")``) and
the emit live here and in ``tui_gateway/server_ki66.py``; the external sync
guard reads both files when that include line is present.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


class ExternalSessionUpdated(BaseModel):
    session_id: str
    role: Optional[str] = None
    previous_session_id: Optional[str] = None


async def notify_external_session_updated(
    request: Request, body: ExternalSessionUpdated, event: str
):
    """Loopback-only bridge for gateway processes that update state.db.

    ki66: the always-on gateway owns state.db but runs in a different process
    from this desktop backend, so a Telegram turn lands in SQLite with nothing
    to tell the open UI. The gateway POSTs here; we re-broadcast over the WS
    the desktop is already listening on, and the client refetches.
    """
    # Resolved at call time through web_server (its public seam for this name).
    from hermes_cli import web_server

    client_host = request.client.host if request.client else ""
    if client_host not in web_server._LOOPBACK_HOST_VALUES:
        raise HTTPException(status_code=403, detail="Forbidden")

    session_id = (body.session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    from tui_gateway.server_ki66 import broadcast_session_external_updated

    await asyncio.to_thread(
        broadcast_session_external_updated,
        {
            "stored_session_id": session_id,
            "role": body.role,
            "previous_session_id": body.previous_session_id,
        },
    )
    return {"ok": True}


router = APIRouter()


@router.post("/internal/session-updated")
async def _session_updated_route(request: Request, body: ExternalSessionUpdated):
    return await notify_external_session_updated(request, body, "session.external_updated")
