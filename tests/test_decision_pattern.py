import json

import httpx
import pytest

from backend.app.decision_pattern import (
    DECIDER_URL, HEALTH_URL, InvestigationState, decide_next_tool,
)

DESCRIPTIONS = {
    "trace_consumers": "Find consumers.",
    "inspect_contract": "Read the contract.",
    "find_related_tests": "Find tests.",
    "inspect_callers": "Inspect callers.",
    "finish_analysis": "Stop.",
}


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def reply(choice, confidence, probabilities=None):
    body = {
        "answers": {"decision": {
            "type": "choice", "choice": choice,
            "probabilities": probabilities or {choice: 1.0}, "confidence": confidence}},
        "latency_ms": 5.0,
    }
    return httpx.Response(200, json=body)


def make_state(**overrides):
    values = dict(change_summary="price changed", changed_symbols=["price"], remaining_steps=5)
    values.update(overrides)
    return InvestigationState(**values)


def test_confident_valid_choice_uses_decider():
    client = mock_client(lambda request: reply("inspect_contract", 0.8))
    d = decide_next_tool(make_state(), DESCRIPTIONS, client=client)
    assert d.chosen == "inspect_contract"
    assert d.source == "decider"
    assert d.confidence == 0.8


def test_low_confidence_falls_back():
    client = mock_client(lambda request: reply("inspect_contract", 0.1))
    d = decide_next_tool(make_state(), DESCRIPTIONS, client=client)
    assert d.source == "fallback"
    assert d.chosen == "trace_consumers"
    assert d.confidence == 0.1
    assert "below" in d.reason


def test_invalid_option_falls_back():
    client = mock_client(lambda request: reply("not_a_tool", 0.9))
    d = decide_next_tool(make_state(), DESCRIPTIONS, client=client)
    assert d.source == "fallback"
    assert "not an allowed option" in d.reason


def test_server_error_falls_back():
    client = mock_client(lambda request: httpx.Response(500))
    d = decide_next_tool(make_state(), DESCRIPTIONS, client=client)
    assert d.source == "fallback"
    assert d.confidence == 0.0


def test_connection_error_falls_back():
    def handler(request):
        raise httpx.ConnectError("server is down", request=request)

    d = decide_next_tool(make_state(), DESCRIPTIONS, client=mock_client(handler))
    assert d.source == "fallback"
    assert d.chosen == "trace_consumers"


def test_used_tools_are_not_offered_again():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return reply("find_related_tests", 0.9)

    state = make_state(tools_run=["trace_consumers", "inspect_contract"])
    d = decide_next_tool(state, DESCRIPTIONS, client=mock_client(handler))
    criteria = seen["questions"]["decision"]["criteria"]
    assert "trace_consumers" not in criteria
    assert "inspect_contract" not in criteria
    assert "finish_analysis" in criteria
    assert d.options == list(criteria)


def test_exhausted_budget_only_offers_finish():
    def handler(request):
        raise AssertionError("the model must not be called")

    d = decide_next_tool(make_state(remaining_steps=0), DESCRIPTIONS, client=mock_client(handler))
    assert d.chosen == "finish_analysis"
    assert d.source == "only_option"


def test_to_step_builds_trace_entry():
    probs = {"trace_consumers": 0.8, "inspect_contract": 0.2}
    client = mock_client(lambda request: reply("trace_consumers", 0.7, probs))
    step = decide_next_tool(make_state(), DESCRIPTIONS, client=client).to_step(3)
    assert step.step == 3
    assert step.chosen == "trace_consumers"
    assert step.fallback_used is False
    assert step.probabilities["trace_consumers"] == 0.8


def server_up():
    try:
        return httpx.get(HEALTH_URL, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not server_up(), reason="Decider 2B server is not running")
def test_live_decision_with_real_model():
    d = decide_next_tool(make_state(), DESCRIPTIONS, url=DECIDER_URL)
    assert d.chosen in DESCRIPTIONS
    assert d.source in ("decider", "fallback")
    if d.source == "decider":
        assert abs(sum(d.probabilities.values()) - 1.0) < 0.01
