# Demo script (about 4 minutes)

**Before you start**: Decider 2B served, backend and frontend running, AWS credentials set. Do one dry run.

1. **The seeded bug (45s)**. Show `demo_repo`: the API contract now returns price in paise; `invoice_service`
   still treats it as rupees. Point out the API tests pass.
2. **Run it (30s)**. In the UI choose the sample repo and click Analyze. Mention the findings are not hardcoded.
3. **Decision trace (60s)**. For each step show the options, the choice and the confidence from Decider 2B.
   Point out any step where confidence was low and the fallback was used (if it happened).
4. **Dependency map (30s)**. Show price linking to invoice service, checkout service and tests.
5. **Findings (45s)**. Invoice service = high risk with evidence (file path, lines). Checkout tests = coverage gap.
6. **Report (30s)**. Show the recommended regression test: 500 rupees equals 50000 paise.
   Show that unsupported claims are not present and that "insufficient evidence" is allowed.
7. **Close (20s)**. Risk is rule-based; the LLM explains; Decider 2B makes a meaningful, auditable decision.

**Backup**: if Bedrock is unreachable, the labeled template report still demonstrates the evidence trail.
If Decider 2B is down, say so. Do not present the dev mock as real.
