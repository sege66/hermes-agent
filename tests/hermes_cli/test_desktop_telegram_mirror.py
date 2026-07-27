"""Desktop→Telegram mirror: turn-completion hook."""

import hermes_cli.desktop_telegram_mirror as mirror


def _capture(monkeypatch, *, desktop="1", toggle=None):
    """Enable the mirror and capture what _send_all would send."""
    monkeypatch.setenv("HERMES_DESKTOP", desktop)
    if toggle is None:
        monkeypatch.delenv("HERMES_DESKTOP_TG_MIRROR", raising=False)
    else:
        monkeypatch.setenv("HERMES_DESKTOP_TG_MIRROR", toggle)

    sent = []
    monkeypatch.setattr(mirror.threading, "Thread", _InlineThread)
    monkeypatch.setattr(mirror, "_send_all", lambda texts: sent.extend(texts))
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


def test_disabled_when_not_desktop_or_toggled_off(monkeypatch):
    sent = _capture(monkeypatch, desktop="0")
    mirror.mirror_turn("hi", "there", "complete")
    assert sent == []

    sent2 = _capture(monkeypatch, toggle="0")
    mirror.mirror_turn("hi", "there", "complete")
    assert sent2 == []
