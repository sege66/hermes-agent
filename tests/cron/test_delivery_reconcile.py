"""Queued cron deliveries must reach a terminal status (ki66 2026-11-19, t595u)."""
from datetime import datetime, timedelta

from cron import delivery_reconcile as rec, executions, jobs
from tools import bot_live_delivery as mailbox


def _finished_run(job_id, outcome="queued", age_hours=0.0):
    ex = executions.create_execution(job_id, source="test")
    executions.mark_execution_running(ex["id"])
    executions.finish_execution(ex["id"], success=True, error=None, delivery_outcome=outcome)
    if age_hours:
        stamp = (datetime.now().astimezone() - timedelta(hours=age_hours)).isoformat()
        with executions._transaction() as conn:
            conn.execute("UPDATE executions SET finished_at=?, started_at=? WHERE id=?", (stamp, stamp, ex["id"]))
    return ex["id"]


def _mark_queued(job_id, execution_id, *, receipt=None):
    def apply(all_jobs, _i, job):
        job["last_status"] = "delivery_queued"
        job["canonical_completions"] = [execution_id]
        job["last_delivery_queued"] = receipt
        jobs.save_jobs(all_jobs)
    jobs._with_job(job_id, apply)


def _receipt(job_id, execution_id, status):
    key, home = rec.receipt_delivery_id(job_id, execution_id, "")
    with mailbox._locked(home) as root:
        mailbox._write(root / f"{key}.json", dict(
            status=status, delivery_id=key, profile_home=str(home), session_id="s", message="m",
            admission_id="a", reply="r", error="", reason=""))
    return {"bot-chat:(own)": {"status": "queued", "delivery_id": key}}


def test_settled_bot_chat_receipt_clears_queued_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="p", schedule="every 1h", deliver="local")
        jobs.update_job(job["id"], {"deliver": "bot-chat"})
        run = _finished_run(job["id"])
        _mark_queued(job["id"], run, receipt=_receipt(job["id"], run, "settled"))
        assert rec.reconcile_queued_deliveries() == 1
        after = jobs.get_job(job["id"])
        assert after["last_status"] == "ok" and not after["last_delivery_queued"]
        assert executions.get_execution(run)["delivery_outcome"] == "delivered"
        assert rec.reconcile_queued_deliveries() == 0  # idempotent


def test_receipt_still_in_flight_is_left_alone_until_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="p", schedule="every 1h", deliver="local")
        jobs.update_job(job["id"], {"deliver": "bot-chat"})
        run = _finished_run(job["id"])
        _mark_queued(job["id"], run, receipt=_receipt(job["id"], run, "claimed"))
        assert rec.reconcile_queued_deliveries() == 0
        assert jobs.get_job(job["id"])["last_status"] == "delivery_queued"
        assert executions.get_execution(run)["delivery_outcome"] == "queued"


def test_stale_or_failed_receipt_is_marked_failed_not_resent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="p", schedule="every 1h", deliver="local")
        jobs.update_job(job["id"], {"deliver": "bot-chat"})
        run = _finished_run(job["id"], age_hours=7)
        _mark_queued(job["id"], run, receipt=_receipt(job["id"], run, "queued"))
        assert rec.reconcile_queued_deliveries() == 1
        after = jobs.get_job(job["id"])
        assert after["last_status"] == "delivery_failed"
        assert "not resent" in after["last_delivery_error"]
        assert executions.get_execution(run)["delivery_outcome"] == "failed"


def test_lost_fire_claim_row_does_not_fence_out_a_delivered_run(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="p", schedule="every 1h", deliver="local")
        run = _finished_run(job["id"], outcome="delivered")
        _mark_queued(job["id"], run)
        lost = executions.create_execution(job["id"], source="builtin")
        executions.finish_execution(lost["id"], success=False, error="Fire claim lost; execution was not started.")
        assert rec.reconcile_queued_deliveries() == 1
        assert jobs.get_job(job["id"])["last_status"] == "ok"


def test_unrelated_job_without_bot_chat_target_is_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="p", schedule="every 1h", deliver="local")
        run = _finished_run(job["id"])
        _mark_queued(job["id"], run)
        assert rec.reconcile_queued_deliveries() == 0
        assert jobs.get_job(job["id"])["last_status"] == "delivery_queued"


def test_old_queued_row_without_queue_row_or_receipt_is_marked_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with jobs.use_cron_store(tmp_path / "cron"):
        job = jobs.create_job(prompt="p", schedule="every 1h", deliver="local")
        old = _finished_run(job["id"], age_hours=30)
        fresh = _finished_run(job["id"], age_hours=1)
        assert rec.reconcile_queued_deliveries() == 1
        assert executions.get_execution(old)["delivery_outcome"] == "failed"
        assert executions.get_execution(fresh)["delivery_outcome"] == "queued"
