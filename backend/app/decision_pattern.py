"""
REUSABLE DECISION PATTERN (hackathon asset): Strands Decider 2B picks one option from a list.

What this module contains
  1. The typed question        QUESTION (ChangeRadar) or any question passed to decide()
  2. Options + descriptions    a dict {option_name: description}, sent as the "criteria"
  3. The state                 plain text; InvestigationState.to_text() is an example
  4. The call + validation     decide() calls the local Decider 2B server and checks the answer
  5. Confidence + fallback     low confidence, an invalid answer or a dead server all fall
                               back to a fixed, predictable order
  6. A reuse example           examples/reuse_triage.py

Use it for any bounded decision:
  from backend.app.decision_pattern import decide
  result = decide(state="...", question="...", options={"a": "...", "b": "..."},
                  fallback_order=["a", "b"])
  result.chosen, result.confidence, result.source   # source: decider / fallback / only_option

Server (separate terminal, separate environment):
  strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device cpu --port 8000
Endpoint: POST /v1/systemone. A choice answer holds: choice, probabilities, confidence.
"""
from dataclasses import dataclass, field

import httpx

DECIDER_URL = "http://127.0.0.1:8000/v1/systemone"
HEALTH_URL = "http://127.0.0.1:8000/health"
MIN_CONFIDENCE = 0.4
QUESTION = "Which investigation tool should run next?"
FALLBACK_PRIORITY = [
    "trace_consumers",
    "inspect_contract",
    "find_related_tests",
    "inspect_callers",
    "finish_analysis",
]
MAX_EVIDENCE_LINES = 8


@dataclass
class Decision:
    chosen: str
    confidence: float
    source: str  # "decider", "fallback" or "only_option"
    reason: str
    options: list
    probabilities: dict = field(default_factory=dict)
    latency_ms: float = None

    def to_step(self, step):
        """Convert to the DecisionStep stored in the report's decision trace."""
        from backend.app.models import DecisionStep

        return DecisionStep(
            step=step,
            options=self.options,
            chosen=self.chosen,
            confidence=self.confidence,
            fallback_used=self.source == "fallback",
            probabilities=self.probabilities,
            reason=self.reason,
            latency_ms=self.latency_ms,
        )


def pick_fallback(names, fallback_order):
    for name in fallback_order or []:
        if name in names:
            return name
    return names[0]


def decide(state, question, options, fallback_order=None, min_confidence=MIN_CONFIDENCE,
           url=DECIDER_URL, timeout=120.0, client=None):
    """Ask Decider 2B to choose one key of `options` ({name: description}) given `state` text."""
    names = list(options)
    if not names:
        raise ValueError("decide() needs at least one option")
    if len(names) == 1:
        return Decision(names[0], 1.0, "only_option",
                        "Only one option is allowed, so no model call was needed", names)

    payload = {
        "state": state,
        "questions": {
            "decision": {"type": "choice", "instructions": question, "criteria": options},
        },
    }
    post = client.post if client is not None else httpx.post
    try:
        response = post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        answer = body["answers"]["decision"]
        chosen = answer["choice"]
        confidence = float(answer["confidence"])
        probabilities = {str(k): float(v) for k, v in answer["probabilities"].items()}
        latency = body.get("latency_ms")
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as error:
        return Decision(
            pick_fallback(names, fallback_order), 0.0, "fallback",
            f"Decider call failed ({type(error).__name__}); used the fixed fallback order", names)

    if chosen not in options:
        return Decision(
            pick_fallback(names, fallback_order), confidence, "fallback",
            f"Decider returned '{chosen}', which is not an allowed option; used the fallback order",
            names, probabilities, latency)
    if confidence < min_confidence:
        return Decision(
            pick_fallback(names, fallback_order), confidence, "fallback",
            f"Confidence {confidence:.2f} is below the threshold {min_confidence:.2f}; "
            f"used the fallback order", names, probabilities, latency)
    return Decision(
        chosen, confidence, "decider",
        f"Decider chose {chosen} with confidence {confidence:.2f}", names, probabilities, latency)


# ---------- ChangeRadar-specific part ----------

@dataclass
class InvestigationState:
    change_summary: str
    changed_symbols: list = field(default_factory=list)
    evidence_found: list = field(default_factory=list)
    unanswered_questions: list = field(default_factory=list)
    tools_run: list = field(default_factory=list)
    remaining_steps: int = 5

    def to_text(self):
        lines = [f"Change under investigation: {self.change_summary}"]
        if self.changed_symbols:
            lines.append("Changed symbols: " + ", ".join(self.changed_symbols))
        lines.append("Tools already run: " + (", ".join(self.tools_run) if self.tools_run else "none"))
        if self.evidence_found:
            lines.append("Evidence found so far:")
            lines.extend(f"- {item}" for item in self.evidence_found[-MAX_EVIDENCE_LINES:])
        else:
            lines.append("Evidence found so far: none")
        if self.unanswered_questions:
            lines.append("Unanswered questions:")
            lines.extend(f"- {item}" for item in self.unanswered_questions)
        lines.append(f"Remaining investigation steps: {self.remaining_steps}")
        return "\n".join(lines)


def decide_next_tool(state, tool_descriptions, **kwargs):
    """Choose the next investigation tool. Tools already run are not offered again."""
    finish_text = tool_descriptions.get("finish_analysis", "Stop investigating.")
    if state.remaining_steps <= 0:
        allowed = {}
    else:
        allowed = {name: text for name, text in tool_descriptions.items()
                   if name not in state.tools_run}
    allowed["finish_analysis"] = finish_text
    kwargs.setdefault("fallback_order", FALLBACK_PRIORITY)
    return decide(state.to_text(), QUESTION, allowed, **kwargs)


def print_decision(title, decision):
    print(f"\n=== {title} ===")
    print(f"options offered : {', '.join(decision.options)}")
    print(f"chosen          : {decision.chosen}")
    print(f"confidence      : {decision.confidence:.2f}")
    print(f"source          : {decision.source}")
    print(f"reason          : {decision.reason}")
    for name, prob in sorted(decision.probabilities.items(), key=lambda kv: -kv[1]):
        print(f"    {name:20s} {prob:.3f}")
    if decision.latency_ms is not None:
        print(f"latency         : {decision.latency_ms:.0f} ms")


def demo():
    # The states below are illustrative inputs for this demo only.
    # In the real loop (Part 7) the state is built from evidence the tools actually found.
    from backend.app.tools import tool_descriptions

    descriptions = tool_descriptions()
    summary = "API field 'price' changed from rupees to paise (500 became 50000)."
    scenarios = [
        ("Start of the investigation", InvestigationState(
            change_summary=summary, changed_symbols=["price"],
            unanswered_questions=["Which components read price?",
                                  "Do they convert paise to rupees?"],
            remaining_steps=5)),
        ("After tracing consumers and reading the contract", InvestigationState(
            change_summary=summary, changed_symbols=["price"],
            evidence_found=["invoice.py line 9: calculate_total reads price directly",
                            "schema.md line 6: contract now says price is in paise",
                            "checkout.py: shipping_fee calls calculate_total (indirect)"],
            unanswered_questions=["Do any tests check the paise convention?"],
            tools_run=["trace_consumers", "inspect_contract"], remaining_steps=3)),
        ("Step budget exhausted", InvestigationState(
            change_summary=summary, changed_symbols=["price"],
            tools_run=["trace_consumers", "inspect_contract", "find_related_tests"],
            remaining_steps=0)),
    ]
    for title, state in scenarios:
        print_decision(title, decide_next_tool(state, descriptions))


if __name__ == "__main__":
    demo()
