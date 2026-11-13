"""Local (ki66) additions split out of the upstream-owned test_codex_transport.py."""

import pytest

from agent.transports import get_transport


@pytest.fixture
def transport():
    import agent.transports.codex
    return get_transport("codex_responses")


@pytest.mark.parametrize("model", ["grok-4.7", "xai/grok-4.7", "x-ai/grok-4.7", "grok-4.6"])
@pytest.mark.parametrize("effort,expected", [("low", "low"), ("medium", "medium"), ("high", "high"), ("xhigh", "xhigh"), ("ultra", "xhigh")])
def test_grok_current_efforts_preserve_priority_boundary(transport, model, effort, expected):
    kw = transport.build_kwargs(
        model=model, messages=[{"role": "user", "content": "Hi"}], tools=[],
        is_xai_responses=True, reasoning_config={"effort": effort},
        request_overrides={"service_tier": "priority"},
    )
    assert kw["reasoning"] == {"effort": expected}
    if model == "grok-4.6":
        assert kw["service_tier"] == "priority"
    else:
        assert "service_tier" not in kw
