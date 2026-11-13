"""Local (ki66) additions split out of the upstream-owned test_model_metadata.py."""

import pytest


@pytest.mark.parametrize("version", ["4.6", "4.7"])
@pytest.mark.parametrize("prefix", ["", "xai/", "x-ai/"])
def test_grok_current_context_effort_and_timeout(version, prefix, tmp_path, monkeypatch):
    """Released 500K models recover old cache entries and retain reasoning support."""
    import agent.model_metadata as mm
    from agent.reasoning_timeouts import get_reasoning_stale_timeout_floor

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    model = f"{prefix}grok-{version}"
    base = "https://api.x.ai/v1"
    mm.save_context_length(model, base, 256_000)
    assert mm.get_model_context_length(model, base_url=base, provider="xai") == 500_000
    assert mm.grok_supports_reasoning_effort(model)
    assert get_reasoning_stale_timeout_floor(model) == 300.0
