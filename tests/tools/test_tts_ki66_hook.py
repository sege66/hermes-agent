"""Regression: the ki66 Korean-reading hook in text_to_speech_tool (2026-11-19).

Upstream 78f3677c7ea dropped the per-call ``provider`` argument; the hook kept passing a name that was
no longer bound (UnboundLocalError on every call, TypeError on the 3-arg _apply_call_overrides).
"""
import inspect
import json

import tools.tts_ki66 as ki66
import tools.tts_tool as tts_tool


def test_hook_signature_has_no_provider_argument():
    assert list(inspect.signature(ki66._ki66_korean_reading).parameters) == ["text", "speed", "voice_id"]


def test_hook_matches_apply_call_overrides_arity():
    params = inspect.signature(tts_tool._apply_call_overrides).parameters
    assert len(params) == 2  # (tts_config, speed): the hook must not pass a provider


def test_hook_resolves_configured_provider_and_rewrites_korean(monkeypatch):
    cfg = {"provider": "korean-cmd",
           "providers": {"korean-cmd": {"type": "command", "command": "true", "language": "ko", "voice": "F5"}}}
    monkeypatch.setattr(tts_tool, "_load_tts_config", lambda: cfg)
    text, error = ki66._ki66_korean_reading("기온 23°C, 하락률 3%", None, None)
    assert error is None
    assert "°C" not in text and "%" not in text and "퍼센트" in text


def test_text_to_speech_tool_does_not_raise_before_synthesis(monkeypatch):
    cfg = {"provider": "korean-cmd",
           "providers": {"korean-cmd": {"type": "command", "command": "true", "language": "ko", "voice": "F5"}}}
    monkeypatch.setattr(tts_tool, "_load_tts_config", lambda: cfg)

    def boom(*_a, **_k):
        raise tts_tool._ChunkFailed("stub: no synthesis in unit test")

    monkeypatch.setattr(tts_tool, "_synthesize_chunks", boom)
    result = json.loads(tts_tool.text_to_speech_tool(text="안녕하세요. 시험입니다."))
    assert result["success"] is False and "stub" in result["error"]
