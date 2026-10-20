# Known limitations

- **One language**: Python only. Other languages are not parsed.
- **One sample architecture**: tuned and tested on the small demo repo; larger repos are untested.
- **Static analysis only**: dynamic dispatch, reflection, runtime config and cross-service network calls can be missed.
- **Risk is an estimate, not proof**: scores come from transparent rules over gathered evidence, not from running the code.
- **Decider 2B is small**: it can choose a suboptimal tool; this is why validation, confidence gating and a fallback exist.
- **Step budget** (5 to 8) can end an investigation before every path is explored; the report lists unresolved questions.
- **Storage**: JSON files, no auth, single user.
- **Local only**: no deployment is provided or tested.
- **Report prose** comes from an LLM; the claim-to-evidence check reduces but cannot eliminate wording errors.
