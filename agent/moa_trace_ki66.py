"""ki66 local: scalar peer-reliability after MoA fan-out (Σ-Mem-inspired).

Local-only module (upstream never touches it). ``agent/moa_trace.py`` re-exports
``emit_moa_peer_reliability`` with a single import line so
``from agent.moa_trace import emit_moa_peer_reliability`` keeps working.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Log-record parity with the origin module.
logger = logging.getLogger("agent.moa_trace")

# Opt out: HERMES_MOA_RELIABILITY=0. Never raises into the live turn.
_RELIABILITY_SCRIPT = Path.home() / "scripts" / "hermes-moa-reliability.py"


def emit_moa_peer_reliability(
    *,
    preset_name: str,
    reference_outputs: list[tuple[str, str, Any]],
    domain: str = "moa",
) -> None:
    """Best-effort write to local peer-reliability (operational ok/fail only).

    Payload is peer labels + boolean ok — no prompt/answer text leaves this
    process on the reliability path. No-op when script missing or
    HERMES_MOA_RELIABILITY=0.
    """
    flag = os.environ.get("HERMES_MOA_RELIABILITY", "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return
    if not _RELIABILITY_SCRIPT.is_file():
        return
    if not reference_outputs:
        return
    try:
        refs: list[dict[str, Any]] = []
        for label, text, acct in reference_outputs:
            peer = str(label or "").strip()
            if not peer and acct is not None:
                prov = getattr(acct, "provider", None) or ""
                model = getattr(acct, "model", None) or ""
                peer = f"{prov}:{model}".strip(":")
            t = str(text or "").strip()
            ok = bool(t) and not t.startswith("[failed:") and not t.lower().startswith(
                "error:"
            )
            refs.append({"peer": peer or "unknown", "ok": ok})
        payload = {
            "domain": domain,
            "preset": preset_name,
            "source": "moa-hook",
            "references": refs,
        }
        subprocess.run(
            [
                sys.executable,
                str(_RELIABILITY_SCRIPT),
                "ingest-run",
                "--json",
                json.dumps(payload, ensure_ascii=False),
            ],
            timeout=8,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # pragma: no cover - must never break a turn
        logger.debug("MoA peer-reliability emit failed: %s", exc)
