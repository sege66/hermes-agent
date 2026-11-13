"""ki66 (local fork) cron additions, kept out of upstream-owned ``cron/jobs.py``.

``cron/jobs.py`` only carries thin hooks into this module so upstream releases
merge without conflicts:

* chat-delivery log (``deliveries.jsonl`` beside ``jobs.json``) that powers the
  desktop chat's read-only cron mirror and ``GET /api/cron/deliveries``;
* strict provider/model pinning (``cron.require_explicit_provider_model``).

Dependency-light on purpose: ``cron.jobs`` imports this module while it is
still initialising, so everything from ``cron.jobs`` is resolved lazily at call
time (which also keeps ``mock.patch("cron.jobs.<name>")`` effective).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List

# Append-only log of what cron jobs actually delivered to a chat (Telegram etc.).
# Script jobs deliver stdout without creating an agent session, so a
# session-derived feed misses them; this captures every real delivery uniformly.
# Bounded; single gateway process writes.
DELIVERIES_FILENAME = "deliveries.jsonl"
MAX_DELIVERIES = 200
_deliveries_lock = threading.Lock()
# Some no_agent scripts colorize stdout; strip ANSI escapes so the mirror reads
# clean (terminal color codes would otherwise render as literal garbage).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _jobs():
    from cron import jobs

    return jobs


def deliveries_file() -> Path:
    """Chat-delivery log of the *current* cron store (beside its jobs.json)."""
    return Path(_jobs()._current_cron_store().cron_dir) / DELIVERIES_FILENAME


def record_cron_delivery(job_id: str, job_name: str, text: str) -> None:
    """Append one delivered cron message to the deliveries log (best-effort).

    Called from the delivery path once a real (non-local) target is resolved, so
    the log mirrors what landed in the chat. Read-modify-write under a lock keeps
    it bounded to the newest ``MAX_DELIVERIES``; deliveries are infrequent so the
    rewrite cost is negligible. Never raises — a logging failure must not break
    delivery.
    """
    jobs = _jobs()
    try:
        text = _ANSI_RE.sub("", text or "").strip()
        if not text:
            return
        entry = {
            "ts": jobs._hermes_now().timestamp(),
            "job_id": job_id,
            "job_name": job_name or job_id,
            "text": text,
        }
        with _deliveries_lock:
            jobs.ensure_dirs()
            existing = jobs.read_cron_deliveries(MAX_DELIVERIES - 1, _locked=True)
            # read_cron_deliveries returns newest-first; persist oldest-first.
            lines = [json.dumps(e, ensure_ascii=False) for e in reversed(existing)]
            lines.append(json.dumps(entry, ensure_ascii=False))
            target = deliveries_file()
            fd, tmp_path = jobs.mkstemp_beside(target, suffix=".tmp", prefix=".deliveries_")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                jobs.atomic_replace(tmp_path, target)
                jobs._secure_file(target)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
    except Exception as exc:  # never break delivery over a logging miss
        jobs.logger.warning("record_cron_delivery failed for %s: %s", job_id, exc)


def read_cron_deliveries(limit: int = 50, _locked: bool = False) -> List[Dict[str, Any]]:
    """Return the most recent cron deliveries, newest first (best-effort)."""
    def _read() -> List[Dict[str, Any]]:
        path = deliveries_file()
        if not path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                with contextlib.suppress(ValueError):
                    out.append(json.loads(line))
        out.reverse()  # newest first
        return out[: max(0, limit)]

    try:
        if _locked:
            return _read()
        with _deliveries_lock:
            return _read()
    except Exception as exc:
        _jobs().logger.warning("read_cron_deliveries failed: %s", exc)
        return []


async def handle_cron_deliveries_request(adapter: Any, request: Any) -> Any:
    """Body of the gateway API server's ``GET /api/cron/deliveries`` (aiohttp).

    Recent cron-job chat deliveries, newest first. Powers the desktop chat's
    read-only cron mirror. Covers script jobs too (they deliver stdout without
    an agent session), which a session-derived feed misses. Auth is applied by
    the ``_require_auth`` wrapper on the route method in ``api_server.py``.
    """
    from aiohttp import web

    limit = adapter._parse_nonnegative_int(request.query.get("limit"), default=50, maximum=200)
    try:
        from cron.jobs import read_cron_deliveries as _read_cron_deliveries

        deliveries = _read_cron_deliveries(limit)
    except Exception as exc:
        logging.getLogger("gateway.platforms.api_server").warning(
            "GET /api/cron/deliveries failed: %s", exc
        )
        deliveries = []
    return web.json_response({"object": "list", "data": deliveries, "limit": limit})


def _strict_cron_model_pinning_enabled() -> bool:
    """Return whether active LLM cron jobs require explicit provider/model."""
    from hermes_cli.config import load_config_readonly

    config = load_config_readonly()
    cron_config = config.get("cron") or {}
    return (
        isinstance(cron_config, dict)
        and cron_config.get("require_explicit_provider_model") is True
    )


def validate_explicit_cron_inference(
    *,
    provider: Any,
    model: Any,
    no_agent: Any,
) -> None:
    """Fail closed when strict policy would persist an unpinned LLM job."""
    if bool(no_agent) or not _strict_cron_model_pinning_enabled():
        return

    normalize = _jobs()._normalize_job_optional_text
    missing = []
    if normalize(provider) is None:
        missing.append("provider")
    if normalize(model) is None:
        missing.append("model")
    if missing:
        raise ValueError(
            "Active LLM cron jobs require explicit provider and model when "
            "cron.require_explicit_provider_model=true; missing: "
            + ", ".join(missing)
        )


def validate_updated_job_inference(updated: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """``update_job`` hook: fail closed when cron.require_explicit_provider_model=true.

    Emergency pause is the one update that must still succeed on an unpinned
    LLM job (pause_job only sends enabled/state/paused_*).
    """
    emergency_pause = (
        not bool(updated.get("enabled", True))
        and updated.get("state") == "paused"
        and set(updates).issubset(
            {"enabled", "state", "paused_at", "paused_reason"}
        )
    )
    if not emergency_pause:
        validate_explicit_cron_inference(
            provider=updated.get("provider"),
            model=updated.get("model"),
            no_agent=updated.get("no_agent"),
        )
