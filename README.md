# ChangeRadar

Evidence-backed change-impact analysis for code changes.

## Problem
A small code change (for example, an API returning price in **paise** instead of **rupees**) can silently break
downstream code that still assumes the old unit. Tests in the changed service pass, so nothing warns the developer.
ChangeRadar reads a Git diff, investigates the real code, and produces a report where every finding points to
file paths and line ranges.

## How it works (short)
1. **Diff ingestion** extracts changed files, symbols, contract files and touched tests (Python AST).
2. **Dependency graph** (NetworkX) links files, functions, endpoints, schemas and tests from real imports, calls and references.
3. **Investigation loop**: at each step **Strands Decider 2B** picks ONE tool from an allowed list and returns a confidence.
   Tools: `trace_consumers`, `inspect_contract`, `find_related_tests`, `inspect_callers`, `finish_analysis`.
4. **Risk scoring** is rule-based and transparent. The LLM never assigns scores.
5. **Amazon Bedrock** writes the report from the evidence and scores. It explains; it does not invent.
6. **Next.js UI** shows the dependency map, decision trace (options, choice, confidence), findings and report.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DECISION_PATTERN.md](docs/DECISION_PATTERN.md).

## Setup (Windows PowerShell, local only)
```powershell
git clone <YOUR_PUBLIC_REPO_URL> changeradar
cd changeradar

# Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

### Configuration
Copy `.env.example` to `.env` and fill in (never commit `.env`):
```
AWS_REGION=<region>
BEDROCK_MODEL_ID=<model id>
AWS_ACCESS_KEY_ID=<...>        # or use an AWS profile
AWS_SECRET_ACCESS_KEY=<...>
DECIDER_ENDPOINT=<how Decider 2B is served>   # TODO: match your Part 6 handoff note
DECIDER_CONFIDENCE_THRESHOLD=<value used in Part 6>
```

### Start Decider 2B
TODO: paste the exact serve command from your Part 6 handoff note.

### Run
```powershell
# Terminal 1 - backend
uvicorn backend.main:app --reload --port 8000     # TODO: confirm module path

# Terminal 2 - frontend
cd frontend
npm run dev                                       # http://localhost:3000
```

## Run the demo
Follow [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). In short: open the UI, choose the **sample repo**,
click **Analyze**, and watch the decision trace, dependency map and report.

## Tests
```powershell
pytest -q
```

## Using Decider 2B in your own project
The reusable module is `TODO: backend/.../decider.py`. A standalone example is in
`TODO: examples/decider_reuse_example.py`. Pattern explained in [docs/DECISION_PATTERN.md](docs/DECISION_PATTERN.md).

## Limitations
See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).


### Confidence threshold
The decision module (`backend/app/decision_pattern.py`) uses `MIN_CONFIDENCE = 0.4`.
If Decider 2B returns a confidence below 0.4, or an option that is not in the allowed
list, the system ignores the model's choice and uses a fixed fallback order.
Every decision (state, options, choice, confidence, fallback used) is logged in the decision trace.
### Start Decider 2B (terminal 1)
Decider 2B runs as a local server on port 8000:

strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device cpu --port 8000

Check that it is running: http://127.0.0.1:8000/health
The backend sends each decision to http://127.0.0.1:8000/v1/systemone.
On CPU, each decision can take several seconds.