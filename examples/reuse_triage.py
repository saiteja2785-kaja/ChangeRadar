"""Reuse example: use decision_pattern for a different decision (support ticket triage)."""
from backend.app.decision_pattern import decide

result = decide(
    state="Help! My payouts have been failing for 3 days.",
    question="Which team should handle this?",
    options={
        "billing": "Payments, invoices, payouts and refunds",
        "technical": "Bugs, errors and outages",
        "sales": "Pricing and new purchases",
    },
    fallback_order=["technical", "billing", "sales"],
    min_confidence=0.5,
)

print("chosen    :", result.chosen)
print("confidence:", round(result.confidence, 2))
print("source    :", result.source)
print("reason    :", result.reason)
