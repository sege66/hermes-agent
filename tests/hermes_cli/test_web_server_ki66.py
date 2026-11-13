"""Local (ki66) additions split out of the upstream-owned test_web_server.py."""

import pytest


class TestWebServerEndpointsKi66:
    """Same TestClient setup as upstream ``TestWebServerEndpoints``."""

    @pytest.fixture(autouse=True)
    def _setup_test_client(self, monkeypatch, _isolate_hermes_home):
        """Create a TestClient and isolate the state DB under the test HERMES_HOME."""
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import hermes_state
        from hermes_constants import get_hermes_home
        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

        monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")

        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_cron_deliveries_are_available_to_the_desktop(self, monkeypatch):
        import cron.jobs as cron_jobs

        expected = [{"ts": 1.0, "job_id": "job-1", "job_name": "Brief", "text": "Done"}]
        monkeypatch.setattr(cron_jobs, "read_cron_deliveries", lambda limit: expected[:limit])

        resp = self.client.get("/api/cron/deliveries?limit=1")

        assert resp.status_code == 200
        assert resp.json() == {"object": "list", "data": expected, "limit": 1}

    def test_platform_scoped_messaging_env_vars_are_channel_managed(self):
        """Platform-scoped vars belong to a Channels card; cross-cutting
        gateway vars belong to the Keys page.

        Uses credentials as the example: the self-configuring knobs
        (*_HOME_CHANNEL, *_ALLOW_ALL_USERS, …) were deliberately dropped from
        the setup cards and handed back to Keys — see
        tests/hermes_cli/test_setup_hidden_env.py.
        """
        from hermes_cli.web_server_messaging import _MESSAGING_KEYS_PAGE_KEYS, _build_catalog_entry, _channel_managed_env_keys

        discord = _build_catalog_entry("discord")
        assert "DISCORD_BOT_TOKEN" in discord["env_vars"]
        assert "DISCORD_ALLOWED_USERS" in discord["env_vars"]

        managed = _channel_managed_env_keys()
        assert "DISCORD_BOT_TOKEN" in managed
        assert "MATTERMOST_TOKEN" in managed
        assert "GATEWAY_PROXY_URL" not in managed
        assert "GATEWAY_PROXY_URL" in _MESSAGING_KEYS_PAGE_KEYS
