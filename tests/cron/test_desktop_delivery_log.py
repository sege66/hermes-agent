"""Desktop must be able to read cron deliveries from the owning profile's store."""

from cron import jobs


def test_delivery_log_persists_appends_and_stays_profile_local(tmp_path):
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"

    with jobs.use_cron_store(primary):
        jobs.record_cron_delivery("first", "First", "\x1b[32mFirst report\x1b[0m")
        jobs.record_cron_delivery("second", "Second", "Second report")

    with jobs.use_cron_store(secondary):
        assert jobs.read_cron_deliveries() == []
        jobs.record_cron_delivery("private", "Private", "Other profile")

    with jobs.use_cron_store(primary):
        deliveries = jobs.read_cron_deliveries()
        assert [(row["job_id"], row["text"]) for row in deliveries] == [
            ("second", "Second report"),
            ("first", "First report"),
        ]
        assert jobs.read_cron_deliveries(1) == deliveries[:1]
