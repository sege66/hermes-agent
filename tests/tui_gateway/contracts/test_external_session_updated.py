"""Local desktop refresh notifications survive the generated wire contract."""

from tui_gateway.contracts.registry import EVENTS


def test_external_session_update_payload_preserves_transcript_routing():
    payload = {
        "stored_session_id": "test-stored-session",
        "previous_session_id": "test-previous-session",
        "role": "assistant",
    }
    model = EVENTS["session.external_updated"].payload
    assert model.model_validate(payload).model_dump() == payload
    payload["previous_session_id"] = None
    payload["role"] = None
    assert model.model_validate(payload).model_dump() == payload
