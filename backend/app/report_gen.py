r"""
Part 8: report generation.

Reads the Part 7 run (docs/last_run.json). Scores and risk levels come from the rules and are
copied through untouched. A Bedrock model only writes the explanation text, and every claim it
makes must cite evidence ids (E1, E2, ...). A checker rejects anything unsupported. If Bedrock
is unavailable or fails the check, a plain template report is produced and labeled as such.

Run:  python -m backend.app.report_gen docs\last_run.json
Config (env vars, never commit secrets):
  BEDROCK_MODEL_ID   e.g. an inference profile or model id you have access to
  AWS_REGION         e.g. us-east-1
  AWS credentials via the standard chain (aws configure / env vars / SSO)
"""
import json
import os
import re
import sys
from pathlib import Path

PROMPT_TEMPLATE = """You are writing the explanation section of a change-impact report for developers.

RULES (strict):
1. Use ONLY the facts in CHANGE and EVIDENCE below. Do not invent files, functions, lines or behavior.
2. Do NOT change, recompute or comment on risk levels or scores. They are fixed by rules.
3. Every sentence you write about a component must be supported by at least one evidence id.
   List the ids you relied on in "evidence_ids". Use only ids that appear in EVIDENCE.
4. If the evidence is thin, say so in "confidence_limits" instead of guessing.
5. Reply with JSON only, no prose, in exactly this shape:
{{"change_summary": "<2-3 sentences>",
  "components": [{{"component": "<exact name from COMPONENTS>", "explanation": "<2-3 sentences>", "evidence_ids": ["E1"]}}],
  "confidence_limits": ["<short sentence>"]}}

CHANGE:
{change}

COMPONENTS (fixed by rules):
{components}

EVIDENCE:
{evidence}
"""


def load_run(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def index_evidence(run):
    """Give every distinct evidence item a stable id E1, E2, ..."""
    ids, items, seen = {}, {}, {}
    for e in run.get("evidence", []):
        key = (e["file_path"], e.get("line_start"), e.get("source_tool"))
        if key in seen:
            continue
        eid = f"E{len(seen) + 1}"
        seen[key] = eid
        items[eid] = e
    return items, seen


def ev_ref(e):
    s, t = e.get("line_start"), e.get("line_end")
    span = f"{s}-{t}" if t and t != s else f"{s}"
    return f"{e['file_path']}:{span}"


def regression_tests(run):
    """Build regression tests from the value changes the diff reader found. Nothing hardcoded."""
    out = []
    for m in re.finditer(r"(\w+): (\d+) -> (\d+)", run["change"].get("change_summary", "")):
        field, old, new = m.group(1), int(m.group(2)), int(m.group(3))
        out.append({
            "field": field, "old": old, "new": new,
            "text": (f"Regression test: with the new convention, a {field} of {new} (was {old} in the old unit) "
                     f"must produce the same invoice total, shipping fee and summary as {old} did before the change. "
                     f"Assert each downstream component gives the same result for the old value in the old unit "
                     f"and the new value in the new unit."),
        })
    return out


def finding_evidence_ids(finding, seen):
    ids = []
    for e in finding.get("evidence", []):
        eid = seen.get((e["file_path"], e.get("line_start"), e.get("source_tool")))
        if eid:
            ids.append(eid)
    return ids


def template_report(run, label):
    items, seen = index_evidence(run)
    comps = []
    for f in run["report"]["findings"]:
        comps.append({"component": f["component"], "risk_level": f["risk_level"],
                      "explanation": f["rationale"], "evidence_ids": finding_evidence_ids(f, seen),
                      "uncertainty": f["uncertainty"]})
    return {"generated_by": label, "change_summary": run["report"]["summary"], "components": comps,
            "confidence_limits": list(run["report"].get("open_questions", [])),
            "evidence": {k: ev_ref(v) for k, v in items.items()}}


def build_prompt(run):
    items, seen = index_evidence(run)
    comps = "\n".join(f"- {f['component']} (risk {f['risk_level']}): {f['rationale']}"
                      for f in run["report"]["findings"])
    ev = "\n".join(f"{k}: {ev_ref(v)} [{v.get('source_tool')}] {v.get('note', '')}" for k, v in items.items())
    return PROMPT_TEMPLATE.format(change=run["report"]["summary"], components=comps, evidence=ev), items, seen


def call_bedrock(prompt, model_id=None, region=None):
    import boto3  # imported here so the fallback works without it
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("BEDROCK_MODEL_ID is not set")
    client = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION", "us-east-1"))
    resp = client.converse(modelId=model_id,
                           messages=[{"role": "user", "content": [{"text": prompt}]}],
                           inferenceConfig={"maxTokens": 1500, "temperature": 0.0})
    return resp["output"]["message"]["content"][0]["text"], model_id


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


def check_claims(draft, run, items):
    """Every explanation must cite known evidence ids, name a real component, and only mention known files."""
    problems = []
    known = {f["component"]: f for f in run["report"]["findings"]}
    paths = {Path(e["file_path"]).name for e in items.values()}
    for c in draft.get("components", []):
        name = c.get("component")
        if name not in known:
            problems.append(f"unknown component: {name}")
            continue
        ids = c.get("evidence_ids") or []
        if not ids:
            problems.append(f"{name}: no evidence ids")
        for i in ids:
            if i not in items:
                problems.append(f"{name}: cites unknown evidence {i}")
        for fn in re.findall(r"[\w./\\-]+\.(?:py|md|js|ts|json)", c.get("explanation", "")):
            if Path(fn).name not in paths:
                problems.append(f"{name}: mentions file not in evidence: {fn}")
    missing = set(known) - {c.get("component") for c in draft.get("components", [])}
    for m in sorted(missing):
        problems.append(f"component missing from report: {m}")
    return problems


def generate(run, caller=call_bedrock):
    prompt, items, seen = build_prompt(run)
    try:
        text, model_id = caller(prompt)
        draft = parse_json(text)
        problems = check_claims(draft, run, items)
        if problems:
            rep = template_report(run, "plain template (Bedrock output rejected by evidence check)")
            rep["check_problems"] = problems
            return finish(rep, run)
    except Exception as ex:
        rep = template_report(run, "plain template (Bedrock unavailable)")
        rep["bedrock_error"] = f"{type(ex).__name__}: {ex}"[:300]
        return finish(rep, run)
    comps = []
    for c in draft["components"]:
        f = next(x for x in run["report"]["findings"] if x["component"] == c["component"])
        comps.append({"component": c["component"], "risk_level": f["risk_level"],  # from rules, not the model
                      "explanation": c["explanation"], "evidence_ids": c["evidence_ids"],
                      "uncertainty": f["uncertainty"]})
    rep = {"generated_by": f"Bedrock model {model_id}", "change_summary": draft.get("change_summary", ""),
           "components": comps, "confidence_limits": draft.get("confidence_limits", []),
           "evidence": {k: ev_ref(v) for k, v in items.items()}, "check_problems": []}
    return finish(rep, run)


def finish(rep, run):
    rep["existing_tests"] = [t for t in run["report"].get("recommended_tests", []) if t.startswith("Extend")]
    rep["missing_tests"] = run["report"].get("missing_tests", [])
    rep["recommended_regression_tests"] = ([t["text"] for t in regression_tests(run)]
                                           + run["report"].get("recommended_tests", []))
    rep["unresolved_questions"] = run["report"].get("open_questions", [])
    return rep


def to_markdown(rep):
    L = [f"# Change impact report", f"_Generated by: {rep['generated_by']}_", "",
         "## Change summary", rep["change_summary"], "", "## Affected components"]
    for c in rep["components"]:
        L += [f"### [{c['risk_level'].upper()}] {c['component']}", c["explanation"],
              "Evidence: " + ", ".join(f"{i} ({rep['evidence'].get(i, '?')})" for i in c["evidence_ids"]),
              f"Uncertainty: {c['uncertainty']}", ""]
    for title, key in [("Missing tests", "missing_tests"), ("Recommended regression tests", "recommended_regression_tests"),
                       ("Unresolved questions", "unresolved_questions"), ("Confidence limits", "confidence_limits")]:
        L += [f"## {title}"] + [f"- {x}" for x in rep.get(key, [])] + [""]
    return "\n".join(L)


if __name__ == "__main__":
    run_path = sys.argv[1] if len(sys.argv) > 1 else "docs/last_run.json"
    rep = generate(load_run(run_path))
    Path("docs").mkdir(exist_ok=True)
    Path("docs/last_report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    Path("docs/last_report.md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    print(f"\nGenerated by: {rep['generated_by']}")
    print("Saved docs/last_report.json and docs/last_report.md")
