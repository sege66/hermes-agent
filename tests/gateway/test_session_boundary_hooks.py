"""Tests that on_session_finalize and on_session_reset plugin hooks fire in the gateway."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.event import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(), message_id="m1")


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner._session_model_overrides = {}
    runner._pending_model_notes = {}
    runner._background_tasks = set()

    session_key = build_session_key(_make_source())
    session_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-old",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    new_session_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-new",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.TELEGRAM,
        chat_type="dm",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = new_session_entry
    runner.session_store.reset_session.return_value = new_session_entry
    runner.session_store._entries = {session_key: session_entry}
    runner.session_store._generate_session_key.return_value = session_key
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = None
    runner._agent_cache_lock = None
    runner._is_user_authorized = lambda _source: True
    runner._format_session_info = lambda: ""

    return runner


@pytest.mark.asyncio
async def test_reset_notifies_desktop_after_topic_binding_with_old_and_new_ids():
    runner = _make_runner()
    runner._async_session_store = MagicMock()
    runner._async_session_store._store = runner.session_store
    runner._async_session_store.reset_session = AsyncMock(
        return_value=runner.session_store.reset_session.return_value
    )
    runner._invalidate_session_run_generation = MagicMock()
    runner._release_running_agent_state = MagicMock()
    runner._evict_cached_agent = MagicMock()
    runner._clear_conversation_scope = MagicMock()
    runner._reset_notice_session_info = MagicMock(return_value="")
    runner._telegram_topic_new_header = MagicMock(return_value="New session")
    runner._is_telegram_topic_lane = MagicMock(return_value=True)

    order: list[str] = []
    runner._record_telegram_topic_binding = MagicMock(
        side_effect=lambda *_args: order.append("bound")
    )

    with (
        patch("gateway.slash_commands_session._notify_desktop_session_updated") as notify,
        patch("hermes_cli.lifecycle.finalize_session"),
        patch("hermes_cli.lifecycle.invoke_hook"),
    ):
        notify.side_effect = lambda *_args, **_kwargs: order.append("notified")
        await runner._handle_reset_command(_make_event("/reset"))

    assert order == ["bound", "notified"]
    notify.assert_called_once_with(
        "sess-new",
        previous_session_id="sess-old",
    )

