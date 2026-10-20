# Requirement checklist

Mark each item only after you have verified it yourself. Leave unverified items unchecked.

- [ ] Public GitHub repository, fresh clone tested
- [ ] Reusable Decider 2B decision module, clearly labeled, with standalone example
- [ ] Real Decider 2B call in the demo (choice and confidence from the model, not mocked)
- [ ] Decision is meaningful (it selects the next tool and changes what evidence is gathered)
- [ ] Output is evidence-backed (every finding has file path and line range)
- [ ] Invalid output and low confidence trigger the fallback (tested)
- [ ] Risk scores come from rules, not the LLM
- [ ] Report can say "insufficient evidence"
- [ ] Every report claim maps to an evidence item (checked)
- [ ] No secrets committed (`.env` ignored, history checked)
- [ ] README setup works on a clean machine
- [ ] Architecture diagram and decision-pattern write-up present
- [ ] Demo script rehearsed
- [ ] Known limitations documented

## Handoff note
Status: TODO
Unverified: TODO
