"""
Part 9: FastAPI backend.

Start (from the repo root, with the venv active):
    uvicorn backend.app.main:app --reload --port 8000

Endpoints
  GET  /health               health check
  GET  /api/sample-diff      the demo diff text (docs/price_paise.diff)
  GET  /api/graph            dependency graph JSON (docs/dependency_graph.json)
  POST /api/runs             start an analysis: {"source": "sample"} or {"source": "diff", "diff_text": "..."}
  GET  /api/runs             list stored runs
  GET  /api/runs/{id}        one run: status, live steps, result, report
Runs are stored as JSON in docs/runs/<id>.json.
"""
import json
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from fastapi.staticfiles import StaticFiles

_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")

app = FastAPI(title="ChangeRadar")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)

DOCS = Path("docs")
RUNS = DOCS / "runs"
SAMPLE_DIFF = DOCS / "price_paise.diff"
GRAPH_FILE = DOCS / "dependency_graph.json"
SAMPLE_SCAN_DIR = "demo_repo"

_lock = threading.Lock()
_live = {}  # run id -> record while running


class RunRequest(BaseModel):
    source: str = "sample"          # "sample" or "diff"
    diff_text: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


def _save(rec):
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{rec['id']}.json").write_text(json.dumps(jsonable_encoder(rec), indent=2), encoding="utf-8")


def _worker(run_id, diff_text):
    rec = _live[run_id]
    try:
        # imported here so the server starts even if a heavy module fails to import
        from backend.app.orchestrator import run_investigation
        from backend.app import report_gen

        def on_step(step, max_steps, decision):
            with _lock:
                rec["steps"].append(jsonable_encoder(decision.to_step(step)))
                rec["max_steps"] = max_steps

        result = run_investigation(diff_text, repo_path=".", scan_dir=SAMPLE_SCAN_DIR, on_step=on_step)
        run_dict = result.to_dict()
        try:
            report = report_gen.generate(run_dict)
        except Exception as ex:  # report problems must not lose the investigation
            report = {"generated_by": "none", "error": f"{type(ex).__name__}: {ex}"}
        with _lock:
            rec.update(status="done", result=run_dict, report=report)
    except Exception as ex:
        with _lock:
            rec.update(status="error", error=f"{type(ex).__name__}: {ex}",
                       trace=traceback.format_exc()[-1500:])
    finally:
        with _lock:
            rec["finished_at"] = datetime.now().isoformat(timespec="seconds")
            _save(rec)


@app.get("/api/sample-diff")
def sample_diff():
    if not SAMPLE_DIFF.exists():
        raise HTTPException(404, "docs/price_paise.diff not found")
    return {"diff_text": SAMPLE_DIFF.read_text(encoding="utf-8")}


@app.get("/api/graph")
def graph():
    if not GRAPH_FILE.exists():
        raise HTTPException(404, "docs/dependency_graph.json not found")
    return json.loads(GRAPH_FILE.read_text(encoding="utf-8"))


@app.post("/api/runs")
def start_run(req: RunRequest):
    if req.source == "sample":
        if not SAMPLE_DIFF.exists():
            raise HTTPException(404, "sample diff missing")
        diff_text = SAMPLE_DIFF.read_text(encoding="utf-8")
    elif req.source == "diff":
        diff_text = (req.diff_text or "").strip()
        if not diff_text:
            raise HTTPException(400, "diff_text is empty")
    else:
        raise HTTPException(400, "source must be 'sample' or 'diff'")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    rec = {"id": run_id, "status": "running", "source": req.source,
           "started_at": datetime.now().isoformat(timespec="seconds"),
           "steps": [], "max_steps": None, "result": None, "report": None, "error": None}
    _live[run_id] = rec
    threading.Thread(target=_worker, args=(run_id, diff_text), daemon=True).start()
    return {"id": run_id}


@app.get("/api/runs")
def list_runs():
    out = []
    for p in sorted(RUNS.glob("*.json"), reverse=True) if RUNS.exists() else []:
        r = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: r.get(k) for k in ("id", "status", "source", "started_at", "finished_at")})
    return out


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    with _lock:
        if run_id in _live:
            return jsonable_encoder(_live[run_id])
    p = RUNS / f"{run_id}.json"
    if not p.exists() or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(404, "run not found")
    return json.loads(p.read_text(encoding="utf-8"))