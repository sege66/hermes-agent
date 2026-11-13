"""Local (ki66) additions split out of the upstream-owned test_scheduler.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cron.scheduler import _deliver_result


class TestCronDeliveryEvidence:
    def _run_standalone(self, send_result):
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}
        send = AsyncMock(return_value=send_result)
        job = {
            "id": "evidence-job",
            "name": "Evidence",
            "deliver": "origin",
            "origin": {"platform": "telegram", "chat_id": "123"},
        }

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("tools.send_message_tool._send_to_platform", new=send), \
             patch("cron.jobs.record_cron_delivery") as record_delivery:
            result = _deliver_result(job, "confirmed content")
        return result, record_delivery

    def test_records_once_after_explicit_success(self):
        result, record_delivery = self._run_standalone({"success": True})

        assert result is None
        record_delivery.assert_called_once_with(
            "evidence-job", "Evidence", "confirmed content"
        )

    @pytest.mark.parametrize(
        "send_result",
        [
            {"success": False},
            {"success": True, "error": "rejected"},
            {},
        ],
    )
    def test_records_nothing_for_unconfirmed_or_failed_results(self, send_result):
        result, record_delivery = self._run_standalone(send_result)

        assert result is not None
        record_delivery.assert_not_called()
