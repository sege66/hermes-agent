"""Local (ki66) additions split out of the upstream-owned test_jobs.py."""

import pytest

from cron.jobs import create_job, get_job, load_jobs, update_job
from tests.cron.test_jobs import tmp_cron_dir  # noqa: F401  (shared fixture)


class TestExplicitInferencePolicy:
    def test_active_agent_jobs_require_provider_and_model(
        self, tmp_cron_dir, monkeypatch
    ):
        monkeypatch.setattr(
            "cron.jobs_ki66._strict_cron_model_pinning_enabled", lambda: True
        )

        with pytest.raises(ValueError, match="missing: provider, model"):
            create_job(prompt="Strict", schedule="every 1h")
        assert load_jobs() == []

        pinned = create_job(
            prompt="Strict",
            schedule="every 1h",
            provider="zai",
            model="glm-5.2",
        )
        script_only = create_job(
            prompt=None,
            schedule="every 1h",
            script="watch.sh",
            no_agent=True,
        )

        with pytest.raises(ValueError, match="missing: provider"):
            update_job(pinned["id"], {"provider": None})

        update_job(pinned["id"], {"enabled": False, "state": "paused"})
        with pytest.raises(ValueError, match="missing: provider"):
            update_job(pinned["id"], {"provider": None})

        persisted = get_job(pinned["id"])
        assert persisted["provider"] == "zai"
        assert persisted["model"] == "glm-5.2"
        assert script_only["no_agent"] is True
