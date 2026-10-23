import { useEffect, useMemo, useState } from "react";
import "./App.css";

// Loose type on purpose: the backend JSON shapes come from the Python models.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Obj = any;

const API = (import.meta.env.VITE_API as string | undefined) ?? (import.meta.env.PROD ? "" : "http://localhost:8001");
async function api(path: string, init?: RequestInit): Promise<Obj> {
  const res = await fetch(API + path, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) msg = String(body.detail);
    } catch {
      /* keep default message */
    }
    throw new Error(msg);
  }
  return res.json();
}

const pct = (n: unknown) => `${Math.round(Number(n ?? 0) * 100)}%`;

/* ---------------- input page ---------------- */
function InputPage({ onStart }: { onStart: (id: string) => void }) {
  const [diff, setDiff] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [runs, setRuns] = useState<Obj[]>([]);

  useEffect(() => {
    api("/api/runs").then(setRuns).catch(() => setRuns([]));
  }, []);

  async function start(body: Obj) {
    setBusy(true);
    setErr("");
    try {
      const r = await api("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      onStart(r.id);
    } catch (e) {
      setErr(String((e as Error).message));
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <h2>Analyze a change</h2>
        <p className="muted">Run the demo change, or paste your own git diff.</p>
        <button disabled={busy} onClick={() => start({ source: "sample" })}>
          {busy ? "Starting..." : "Run the sample change (price: rupees to paise)"}
        </button>
      </section>
      <section className="card">
        <h3>Or paste a diff</h3>
        <textarea
          rows={10}
          placeholder="diff --git a/... b/..."
          value={diff}
          onChange={(e) => setDiff(e.target.value)}
        />
        <button
          disabled={busy || !diff.trim()}
          onClick={() => start({ source: "diff", diff_text: diff })}
        >
          Analyze pasted diff
        </button>
        <p className="muted small">Pasted diffs are analyzed against the demo repo's code.</p>
      </section>
      {err && <div className="banner error">Could not start: {err}</div>}
      {runs.length > 0 && (
        <section className="card">
          <h3>Previous runs</h3>
          <ul className="plain">
            {runs.map((r) => (
              <li key={r.id}>
                <a href={`#/run/${r.id}`}>{r.id}</a> <span className="muted">({r.status})</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/* ---------------- dependency map ---------------- */
function nodeId(n: Obj): string {
  return String(n.id ?? n.name ?? n.label ?? "");
}
function endId(e: Obj): string {
  return typeof e === "object" && e !== null ? nodeId(e) : String(e);
}

function DependencyMap({ findings }: { findings: Obj[] }) {
  const [graph, setGraph] = useState<Obj>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api("/api/graph").then(setGraph).catch((e) => setErr(String(e.message)));
  }, []);

  const view = useMemo(() => {
    if (!graph) return null;
    const nodes: Obj[] = graph.nodes ?? [];
    const edges: Obj[] = graph.links ?? graph.edges ?? [];
    const adj = new Map<string, Set<string>>();
    const add = (a: string, b: string) => {
      if (!adj.has(a)) adj.set(a, new Set());
      adj.get(a)!.add(b);
    };
    edges.forEach((e) => {
      const s = endId(e.source);
      const t = endId(e.target);
      add(s, t);
      add(t, s);
    });
    const byId = new Map<string, Obj>(nodes.map((n) => [nodeId(n), n]));
    const roots = nodes.map(nodeId).filter((id) => id.toLowerCase().includes("price"));
    const depth = new Map<string, number>();
    let frontier = roots;
    roots.forEach((r) => depth.set(r, 0));
    for (let d = 1; d <= 2; d++) {
      const next: string[] = [];
      frontier.forEach((id) =>
        (adj.get(id) ?? new Set<string>()).forEach((nb) => {
          if (!depth.has(nb)) {
            depth.set(nb, d);
            next.push(nb);
          }
        }),
      );
      frontier = next;
    }
    const ids = [...depth.keys()].slice(0, 40);
    const cols: string[][] = [[], [], []];
    ids.forEach((id) => cols[depth.get(id)!].push(id));
    const pos = new Map<string, { x: number; y: number }>();
    cols.forEach((col, ci) =>
      col.forEach((id, ri) => pos.set(id, { x: 20 + ci * 330, y: 20 + ri * 44 })),
    );
    const risk = new Map<string, string>();
    findings.forEach((f) => {
      const [file, fn] = String(f.component).split("::");
      const base = file.split("/").pop() ?? file;
      ids.forEach((id) => {
        const hay = id + " " + JSON.stringify(byId.get(id) ?? {});
        if (fn && hay.includes(fn) && hay.includes(base)) risk.set(id, f.risk_level);
      });
    });
    const shown = edges.filter((e) => pos.has(endId(e.source)) && pos.has(endId(e.target)));
    const height = 40 + Math.max(...cols.map((c) => c.length), 1) * 44;
    return { ids, pos, shown, risk, byId, height, total: nodes.length, roots };
  }, [graph, findings]);

  if (err) return <div className="banner error">Could not load graph: {err}</div>;
  if (!view) return <p className="muted">Loading dependency map...</p>;
  if (view.ids.length === 0)
    return (
      <div className="banner warn">
        No nodes related to "price" were found in the graph ({view.total} nodes total). The graph
        format may differ from what this page expects.
      </div>
    );

  return (
    <div>
      <p className="muted small">
        Everything within 2 hops of the changed field. Colored boxes are components with findings.
      </p>
      <div className="mapwrap">
        <svg width={1020} height={view.height}>
          {view.shown.map((e, i) => {
            const a = view.pos.get(endId(e.source))!;
            const b = view.pos.get(endId(e.target))!;
            return (
              <line key={i} x1={a.x + 300} y1={a.y + 15} x2={b.x} y2={b.y + 15} className="edge" />
            );
          })}
          {view.ids.map((id) => {
            const p = view.pos.get(id)!;
            const label = String(view.byId.get(id)?.label ?? id);
            const cls = view.risk.get(id) ?? (view.roots.includes(id) ? "root" : "none");
            return (
              <g key={id} className={`node ${cls}`}>
                <rect x={p.x} y={p.y} width={300} height={30} rx={6} />
                <text x={p.x + 8} y={p.y + 20}>
                  {label.length > 44 ? "..." + label.slice(-41) : label}
                </text>
                <title>{id}</title>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="legend">
        <span className="dot root" /> Changed field (where the change starts)
        <span className="dot high" /> High risk (score 10 or more)
        <span className="dot medium" /> Medium risk (score 5 to 9)
        <span className="dot low" /> Low risk (score under 5)
        <span className="dot none" /> Related code, no finding
      </div>
      <p className="muted small">
        Risk score = points for how directly the code reads the changed field, whether the contract
        changed, whether the code adapts, whether it does calculations, test coverage, and callers.
        It is an estimate from the code, not proof of a failure.
      </p>
    </div>
  );
}

/* ---------------- decision trace ---------------- */
function Trace({ steps, max }: { steps: Obj[]; max: number | null }) {
  if (steps.length === 0) return <p className="muted">Waiting for the first decision...</p>;
  return (
    <div className="stack">
      {steps.map((s, i) => {
        const options = s.options ?? s.candidates ?? s.allowed_tools ?? [];
        return (
          <div className="card" key={i}>
            <div className="row">
              <strong>
                Step {s.step ?? i + 1}
                {max ? ` of ${max}` : ""}: {s.chosen ?? s.tool}
              </strong>
              <span className="chip">{s.source ?? "decider"}</span>
            </div>
            <div className="bar">
              <div style={{ width: pct(s.confidence) }} />
            </div>
            <div className="muted small">confidence {pct(s.confidence)}</div>
            {Array.isArray(options) && options.length > 0 && (
              <div className="small">
                Options:{" "}
                {options.map((o: Obj, j: number) => (
                  <span className={`chip ${String(o) === String(s.chosen) ? "pick" : ""}`} key={j}>
                    {String(o)}
                  </span>
                ))}
              </div>
            )}
            {s.reason && <p className="small">{s.reason}</p>}
          </div>
        );
      })}
    </div>
  );
}

/* ---------------- findings ---------------- */
function Findings({ findings }: { findings: Obj[] }) {
  if (findings.length === 0)
    return <div className="banner warn">Insufficient evidence: no components could be scored.</div>;
  return (
    <div className="stack">
      {findings.map((f, i) => (
        <div className="card" key={i}>
          <div className="row">
            <span className={`badge ${f.risk_level}`}>{String(f.risk_level).toUpperCase()} RISK</span>
            <code>{f.component}</code>
          </div>
          <p className="small">{f.rationale}</p>
          <ul className="plain small">
            {(f.evidence ?? []).map((e: Obj, j: number) => (
              <li key={j}>
                <code>
                  {e.file_path}:{e.line_start}
                  {e.line_end && e.line_end !== e.line_start ? `-${e.line_end}` : ""}
                </code>{" "}
                <span className="muted">({e.source_tool})</span>
              </li>
            ))}
          </ul>
          <p className="muted small">Uncertainty: {f.uncertainty}</p>
        </div>
      ))}
    </div>
  );
}

/* ---------------- report ---------------- */
function ReportView({ report }: { report: Obj }) {
  if (!report) return <p className="muted">Report not ready yet.</p>;
  if (report.error) return <div className="banner error">Report failed: {report.error}</div>;
  const isTemplate = String(report.generated_by).startsWith("plain template");
  const list = (title: string, items?: string[]) =>
    items && items.length > 0 ? (
      <section className="card">
        <h3>{title}</h3>
        <ul className="small">
          {items.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      </section>
    ) : null;
  return (
    <div className="stack">
      <div className={`banner ${isTemplate ? "warn" : "ok"}`}>
        Generated by: {report.generated_by}
        {isTemplate && " (fixed template, not the AI model)"}
      </div>
      <section className="card">
        <h3>Change summary</h3>
        <p className="small">{report.change_summary}</p>
      </section>
      {(report.components ?? []).map((c: Obj, i: number) => (
        <section className="card" key={i}>
          <div className="row">
            <span className={`badge ${c.risk_level}`}>{String(c.risk_level).toUpperCase()} RISK</span>
            <code>{c.component}</code>
          </div>
          <p className="small">{c.explanation}</p>
          <div className="small muted">
            Evidence:{" "}
            {(c.evidence_ids ?? []).map((id: string) => (
              <span className="chip" key={id} title={report.evidence?.[id]}>
                {id} {report.evidence?.[id]}
              </span>
            ))}
          </div>
        </section>
      ))}
      {list("Missing tests", report.missing_tests)}
      {list("Recommended regression tests", report.recommended_regression_tests)}
      {list("Unresolved questions", report.unresolved_questions)}
      {list("Confidence limits", report.confidence_limits)}
    </div>
  );
}

/* ---------------- run page ---------------- */
const TABS = ["Dependency map", "Decision trace", "Findings", "Report"] as const;

function RunPage({ id }: { id: string }) {
  const [run, setRun] = useState<Obj>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Decision trace");

  useEffect(() => {
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const r = await api(`/api/runs/${id}`);
        if (stop) return;
        setRun(r);
        setErr("");
        if (r.status === "running") timer = window.setTimeout(tick, 2000);
      } catch (e) {
        if (!stop) setErr(String((e as Error).message));
      }
    };
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  if (err) return <div className="banner error">Could not load run: {err}</div>;
  if (!run) return <p className="muted">Loading...</p>;

  const findings: Obj[] = run.result?.report?.findings ?? [];
  return (
    <div className="stack">
      <div className="row">
        <h2>Run {run.id}</h2>
        <span className={`chip ${run.status}`}>{run.status}</span>
      </div>
      {run.status === "running" && (
        <div className="banner">
          Investigating... each decision can take several seconds. Steps so far: {run.steps.length}
        </div>
      )}
      {run.status === "error" && (
        <div className="banner error">
          The analysis failed: {run.error}
          {run.trace && <pre>{run.trace}</pre>}
        </div>
      )}
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Dependency map" && <DependencyMap findings={findings} />}
      {tab === "Decision trace" && <Trace steps={run.steps} max={run.max_steps} />}
      {tab === "Findings" &&
        (run.status === "done" ? <Findings findings={findings} /> : <p className="muted">Waiting for the analysis to finish...</p>)}
      {tab === "Report" && <ReportView report={run.report} />}
    </div>
  );
}

/* ---------------- app shell ---------------- */
export default function App() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const m = hash.match(/^#\/run\/(.+)$/);
  return (
    <div className="app">
      <header>
        <a href="#/" className="brand">
          ChangeRadar
        </a>
        <span className="muted small">evidence-backed change impact</span>
      </header>
      <main>{m ? <RunPage id={m[1]} /> : <InputPage onStart={(id) => (window.location.hash = `#/run/${id}`)} />}</main>
    </div>
  );
}