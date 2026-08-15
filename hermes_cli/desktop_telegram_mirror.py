"""Mirror desktop-app chat turns to Telegram in real time.

Symmetric other half of the read-only Telegram→desktop merge: a turn typed in
the desktop chat — and the assistant's reply — is pushed to the Telegram home
channel tagged ``🖥 데스크톱`` so the same conversation is visible on the phone.

Called from ``tui_gateway._run_prompt_submit`` (the desktop backend's turn loop)
right after a turn completes. That handler only runs for turns typed in the
desktop app — phone-originated turns are handled by the separate always-on
gateway and are already on Telegram — so there is no echo. The send goes out via
the standalone ``_send_to_platform`` path; a bot never re-receives its own sends
and nothing is written to a Telegram session, so the read-direction merge does
not re-display these either.

Gated on ``HERMES_DESKTOP=1`` (the desktop app backend). ``HERMES_DESKTOP_TG_MIRROR=0``
turns it off.

ponytail: always targets the Telegram home channel (the user's own DM). If a
desktop session is ever bound to a different Telegram chat/group, resolve the
chat_id from the session origin instead.
"""

import asyncio
import logging
import os
import threading

_log = logging.getLogger(__name__)

_MARKER_USER = "🖥 데스크톱 · 나"
_MARKER_ASSISTANT = "🖥 데스크톱 · 헤르메스"

_target = None  # cached only after a valid (Platform, pconfig, chat_id, thread_id) resolves


def _enabled() -> bool:
    return (
        os.getenv("HERMES_DESKTOP") == "1"
        and os.getenv("HERMES_DESKTOP_TG_MIRROR", "1") != "0"
    )


def _resolve_target():
    """Resolve and cache a valid Telegram home target."""
    global _target
    if _target is not None:
        return _target
    try:
        from cron.scheduler import _get_home_target_chat_id, _get_home_target_thread_id
        from gateway.config import Platform, load_gateway_config

        config = load_gateway_config()
        pconfig = config.platforms.get(Platform.TELEGRAM)
        chat_id = _get_home_target_chat_id("telegram")
        thread_id = _get_home_target_thread_id("telegram")
    except Exception as exc:
        _log.debug("Desktop→Telegram mirror: target resolve failed: %s", exc)
        return None

    if not pconfig or not getattr(pconfig, "enabled", False) or not chat_id:
        _log.info("Desktop→Telegram mirror: no enabled Telegram home channel; idle")
        return None

    _target = (Platform.TELEGRAM, pconfig, chat_id, thread_id)
    _log.info("Desktop→Telegram mirror: target resolved")
    return _target


def _send_all(texts) -> bool:
    """Send each text to Telegram, sequentially, in this (background) thread."""
    target = _resolve_target()
    if not target:
        return False
    platform, pconfig, chat_id, thread_id = target
    from cron.scheduler import _confirm_adapter_delivery
    from tools.send_message_tool import _send_to_platform

    delivered = True
    for text in texts:
        try:
            result = asyncio.run(
                _send_to_platform(platform, pconfig, chat_id, text, thread_id=thread_id)
            )
            if not _confirm_adapter_delivery(result):
                delivered = False
                _log.warning("Desktop→Telegram mirror send was not confirmed")
        except Exception as exc:
            delivered = False
            _log.debug("Desktop→Telegram mirror send failed: %s", exc)
    return delivered


def mirror_turn(user_text, assistant_text, status: str) -> None:
    """Push a completed desktop chat turn (user prompt + reply) to Telegram.

    Fire-and-forget on a daemon thread so the Telegram round-trip never blocks
    the desktop turn loop. No-op unless enabled and the turn completed cleanly.
    """
    if not _enabled() or status != "complete":
        return

    texts = []
    for marker, body in ((_MARKER_USER, user_text), (_MARKER_ASSISTANT, assistant_text)):
        body = body.strip() if isinstance(body, str) else ""
        if body:
            texts.append(f"{marker}\n{body}")
    if not texts:
        return

    threading.Thread(
        target=_send_all, args=(texts,), daemon=True, name="desktop-telegram-mirror"
    ).start()
