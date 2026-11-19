"""Write Bot Chat receipt outcomes (and fire-claim-fenced runs) back onto cron bookkeeping.

ki66 2026-11-19 (t595u). Two ways a finished run kept reading "delivery still in progress" forever:

1. **Bot Chat receipts.** ``deliver: ...,bot-chat:<profile>`` hands the payload to the live owner and books
   ``last_status="delivery_queued"`` + ledger ``delivery_outcome="queued"``. The owner settles the receipt
   (``tools.bot_live_delivery``) minutes later, but ``cron.delivery_outcome`` only consults the
   ``cron/deliveries.db`` queue row, which Bot Chat targets never have. Nothing ever re-read the receipt,
   so every run stayed "queued" (12 daily runs of one job, ledger rows back to 11-06).
2. **Lost fire claims.** ``_settle_job_record`` fences on the *latest* execution row. A later scheduler
   tick may add a ``failed`` / ``Fire claim lost; execution was not started`` row (never started, no side
   effects) which then fenced the real run out, so a ``delivered`` ledger row never reached jobs.json.

``reconcile_queued_deliveries`` runs from the tick's housekeeping. It is idempotent, only moves a
``queued`` outcome to a terminal one, never resends anything, and marks a receipt that stays
non-terminal past ``STALE_AFTER_SECONDS`` as ``delivery_failed`` (completion unverified, not resent)
so a stuck hand-off becomes visible instead of silent.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

STALE_AFTER_SECONDS = 6 * 3600
_RECEIPT_FAILED = frozenset({"failed", "cancelled", "ambiguous"})
_SCAN_LIMIT = 300
ORPHAN_AFTER_SECONDS = 24 * 3600


def bot_chat_profiles(deliver: Any) -> list[str]:
    """Profile args of every ``bot-chat[:profile]`` token in a job's ``deliver`` ('' = own profile)."""
    if isinstance(deliver, (list, tuple)):
        parts = [str(p) for p in deliver]
    else:
        parts = str(deliver or "").split(",")
    out = []
    for part in parts:
        part = part.strip()
        if part == "bot-chat" or part.startswith("bot-chat:"):
            out.append(part.partition(":")[2].strip())
    return out


def receipt_delivery_id(job_id: str, execution_id: str, profile: str) -> tuple[str, Path]:
    """The Bot Chat delivery id ``_deliver_to_bot_chat`` derived for this run, and the home it targets."""
    from hermes_constants import get_hermes_home
    from hermes_cli.profiles import get_profile_dir

    source_home = get_hermes_home().resolve()
    home = (get_profile_dir(profile) if profile else source_home).resolve()
    key = hashlib.sha256(json.dumps(
        [str(source_home), job_id, str(execution_id), str(home)],
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return key, home


def _age_seconds(stamp: Optional[str]) -> Optional[float]:
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
        return (datetime.now(then.tzinfo) - then).total_seconds()
    except (TypeError, ValueError):
        return None


def _receipt_verdict(job: dict, execution: dict) -> Optional[tuple[str, Optional[str]]]:
    """``(ledger_outcome, error)`` once every Bot Chat receipt of the run is terminal, else None."""
    from tools.bot_live_delivery import read_delivery_result

    profiles = bot_chat_profiles(job.get("deliver"))
    if not profiles:
        return None
    failures, pending = [], []
    for profile in profiles:
        did, home = receipt_delivery_id(job["id"], execution["id"], profile)
        record = read_delivery_result(home, did)
        status = (record or {}).get("status")
        label = f"bot-chat:{profile or '(own)'}"
        if status == "settled":
            continue
        if status in _RECEIPT_FAILED:
            failures.append(f"{label} receipt {did[:12]} {status}")
        else:
            pending.append(f"{label} receipt {did[:12]} {status or 'missing'}")
    if pending:
        age = _age_seconds(execution.get("finished_at") or execution.get("started_at"))
        if age is None or age < STALE_AFTER_SECONDS:
            return None
        failures.extend(f"{p} after {int(age // 3600)}h: completion unverified, not resent" for p in pending)
    if failures:
        return "failed", "; ".join(failures)
    return "delivered", None


def _real_runs(job_id: str, limit: int = 10) -> list[dict]:
    """Newest-first executions that actually started (a lost fire claim never ran anything)."""
    from cron.executions import list_executions

    return [e for e in list_executions(job_id=job_id, limit=limit) if e.get("started_at")]


def _stamp_job(job_id: str, execution_id: str, outcome: str, error: Optional[str]) -> bool:
    """Move ``delivery_queued`` to its real status on the job record, only for the run's own record."""
    from cron.jobs import _with_job, save_jobs
    from cron.jobs_error_text import sanitize_persisted_error

    error = sanitize_persisted_error(error)

    def apply(jobs, _i, job):
        if job.get("last_status") != "delivery_queued":
            return False
        completions = job.get("canonical_completions") or []
        if completions and completions[-1] != execution_id:
            return False
        job["last_status"] = "delivery_failed" if outcome == "failed" else "ok"
        job["last_delivery_error"] = error
        job["last_delivery_queued"] = None
        save_jobs(jobs)
        return True

    return bool(_with_job(job_id, apply, missing=False))


def reconcile_queued_deliveries() -> int:
    """Settle ``queued`` ledger rows whose real outcome is already known. Returns rows settled."""
    from cron.executions import settle_delivery_outcome
    from cron.jobs import load_jobs

    settled = 0
    jobs = {j.get("id"): j for j in load_jobs()}
    for job_id, job in jobs.items():
        if not job_id or not bot_chat_profiles(job.get("deliver")):
            continue
        for execution in _real_runs(job_id, limit=_SCAN_LIMIT if job.get("last_status") != "delivery_queued" else 30):
            if execution.get("delivery_outcome") != "queued":
                continue
            verdict = _receipt_verdict(job, execution)
            if verdict is None:
                continue
            outcome, error = verdict
            if settle_delivery_outcome(execution["id"], outcome):
                settled += 1
                logger.info("Cron delivery %s (job %s): Bot Chat outcome %s written back", execution["id"], job_id, outcome)
            newest = _newest(job_id)
            if newest and newest["id"] == execution["id"]:
                _stamp_job(job_id, execution["id"], outcome, error)
                if outcome == "failed":
                    logger.warning("Cron job %s: Bot Chat delivery marked failed: %s", job_id, error)
    settled += _reconcile_fenced_out_jobs(list(jobs.values()))
    settled += _reconcile_orphan_queued()
    return settled


def _newest(job_id: str) -> Optional[dict]:
    runs = _real_runs(job_id, limit=10)
    return runs[0] if runs else None


def _reconcile_fenced_out_jobs(jobs: list[dict]) -> int:
    """Jobs stuck on ``delivery_queued`` while the ledger already holds a terminal outcome for their
    newest real run (a lost-fire-claim row had fenced it out)."""
    fixed = 0
    for job in jobs:
        if job.get("last_status") != "delivery_queued" or job.get("last_delivery_queued"):
            continue
        run = _newest(job["id"])
        if not run or run.get("delivery_outcome") not in ("delivered", "suppressed", "failed"):
            continue
        outcome = "failed" if run["delivery_outcome"] == "failed" else "delivered"
        error = "delivery failed (see execution ledger)" if outcome == "failed" else None
        if _stamp_job(job["id"], run["id"], outcome, error):
            fixed += 1
            logger.info("Cron job %s: delivery_queued cleared (ledger outcome %s)", job["id"], run["delivery_outcome"])
    return fixed


def _reconcile_orphan_queued() -> int:
    """``queued`` ledger rows older than a day that no queue row and no receipt can ever settle.

    Marked ``failed`` (hand-off unverified, never resent) so they stop reading as in-progress.
    """
    from cron.delivery_queue import get_status
    from cron.executions import _transaction, settle_delivery_outcome

    with _transaction() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, job_id, finished_at FROM executions WHERE delivery_outcome='queued' "
            "AND started_at IS NOT NULL AND finished_at IS NOT NULL")]
    settled = 0
    for row in rows:
        age = _age_seconds(row.get("finished_at"))
        if age is None or age < ORPHAN_AFTER_SECONDS or get_status(row["id"]) is not None:
            continue
        if settle_delivery_outcome(row["id"], "failed"):
            settled += 1
            logger.warning(
                "Cron execution %s (job %s): queued delivery has no queue row or receipt after %.0fh; "
                "marked failed (unverified, not resent)", row["id"], row["job_id"], age / 3600)
    return settled


def reconcile_quietly() -> None:
    """Housekeeping must never stop due jobs from running."""
    try:
        reconcile_queued_deliveries()
    except Exception:
        logger.warning("Cron delivery reconcile failed", exc_info=True)
