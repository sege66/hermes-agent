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


class TestLiveLaneEvidence:
    """The live lane counts only a confirmed text send (not a confirmation timeout)."""

    @pytest.mark.parametrize(
        "send_text_result, delivered, expected",
        [
            ((True, False, "m1"), True, True),
            ((True, True, None), True, False),   # assume-delivered, no evidence
            ((False, False, None), False, False),
            ((True, False, "m1"), False, False),  # text ok, lane failed afterwards
        ],
    )
    def test_confirmation_requires_text_evidence(self, send_text_result, delivered, expected):
        from cron import scheduler_delivery_ki66 as ki66

        send_text = ki66._wrap_live_send_text(lambda: send_text_result)

        def lane():
            send_text()
            return delivered

        ki66._run.state = state = {"confirmed": False, "live_text_confirmed": False}
        try:
            assert ki66._wrap_live_adapter(lane)() is delivered
        finally:
            ki66._run.state = None
        assert state["confirmed"] is expected

    def test_in_band_error_dict_is_rejected(self):
        import cron.scheduler_delivery  # noqa: F401
        from cron import scheduler_delivery_ki66 as ki66

        assert ki66.confirm_delivery({"success": True, "message_id": 1, "error": "x"}) is False
        assert ki66.confirm_delivery({"success": True, "message_id": 1}) is True
