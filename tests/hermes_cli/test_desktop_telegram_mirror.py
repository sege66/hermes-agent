"""Desktop→Telegram mirror: turn-completion hook."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import hermes_cli.desktop_telegram_mirror as mirror


def _capture(monkeypatch, *, desktop="1", toggle=None):
    """Enable the mirror and capture what _send_all would send."""
    monkeypatch.setenv("HERMES_DESKTOP", desktop)
    if toggle is None:
        monkeypatch.delenv("HERMES_DESKTOP_TG_MIRROR", raising=False)
    else:
        monkeypatch.setenv("HERMES_DESKTOP_TG_MIRROR", toggle)

    sent = []

    def _fake(texts, media_files=None):
        sent.extend(texts)
        if media_files:
            sent.append(("media", tuple(media_files)))
        return True

    monkeypatch.setattr(mirror.threading, "Thread", _InlineThread)
    monkeypatch.setattr(mirror, "_send_all", _fake)
    return sent


class _InlineThread:
    def __init__(self, target=None, args=(), **_kwargs):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def test_mirror_turn_sends_user_and_assistant(monkeypatch):
    sent = _capture(monkeypatch)
    mirror.mirror_turn("내일 일정 알려줘", "대표님, 내일 일정입니다…", "complete")
    assert sent == [
        "🖥 데스크톱 · 나\n내일 일정 알려줘",
        "🖥 데스크톱 · 헤르메스\n대표님, 내일 일정입니다…",
    ]


def test_skips_non_complete_and_empty(monkeypatch):
    sent = _capture(monkeypatch)
    mirror.mirror_turn("hi", "partial...", "error")
    mirror.mirror_turn("", "  ", "complete")
    assert sent == []

    mirror.mirror_turn("only question", "", "complete")
    assert sent == ["🖥 데스크톱 · 나\nonly question"]


def test_mirror_turn_attaches_existing_images_on_user_send(monkeypatch, tmp_path):
    img = tmp_path / "shot.jpg"
    img.write_bytes(b"jpeg")
    missing = tmp_path / "gone.jpg"
    sent = _capture(monkeypatch)
    mirror.mirror_turn("사진", "답", "complete", images=[str(img), str(missing), 12])
    assert sent[0] == "🖥 데스크톱 · 나\n사진"
    assert sent[1] == "🖥 데스크톱 · 헤르메스\n답"
    assert sent[2] == ("media", ((str(img), False),))


def test_mirror_turn_photo_only_uses_user_marker(monkeypatch, tmp_path):
    img = tmp_path / "only.png"
    img.write_bytes(b"png")
    sent = _capture(monkeypatch)
    mirror.mirror_turn("  ", "", "complete", images=[str(img)])
    assert sent[0] == "🖥 데스크톱 · 나"
    assert sent[1] == ("media", ((str(img), False),))


def test_disabled_when_not_desktop_or_toggled_off(monkeypatch):
    sent = _capture(monkeypatch, desktop="0")
    mirror.mirror_turn("hi", "there", "complete")
    assert sent == []

    sent2 = _capture(monkeypatch, toggle="0")
    mirror.mirror_turn("hi", "there", "complete")
    assert sent2 == []


def test_target_resolution_retries_after_temporary_unavailability(monkeypatch):
    from cron import scheduler
    from gateway.config import Platform
    import gateway.config

    chat_ids = iter([None, "123"])
    monkeypatch.setattr(scheduler, "_get_home_target_chat_id", lambda _platform: next(chat_ids))
    monkeypatch.setattr(scheduler, "_get_home_target_thread_id", lambda _platform: None)
    monkeypatch.setattr(
        gateway.config,
        "load_gateway_config",
        lambda: SimpleNamespace(
            platforms={Platform.TELEGRAM: SimpleNamespace(enabled=True)}
        ),
    )
    monkeypatch.setattr(mirror, "_target", None)

    assert mirror._resolve_target() is None
    resolved = mirror._resolve_target()
    assert resolved is not None
    assert resolved[0] == Platform.TELEGRAM
    assert resolved[1].enabled is True
    assert resolved[2:] == ("123", None)


@pytest.mark.parametrize(
    ("send_result", "expected"),
    [
        ({"success": True}, True),
        ({"success": True, "error": "rejected"}, False),
        ({"success": False}, False),
        ({}, False),
    ],
)
def test_send_all_requires_explicit_success(monkeypatch, send_result, expected):
    monkeypatch.setattr(mirror, "_resolve_target", lambda: ("telegram", object(), "123", None))
    send = AsyncMock(return_value=send_result)
    monkeypatch.setattr("tools.send_message_tool._send_to_platform", send)

    assert mirror._send_all(["hello"]) is expected
