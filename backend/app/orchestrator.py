"""
Part 7: the investigation loop.

  state -> Decider 2B picks a tool -> run the tool -> add evidence -> repeat
until the Decider finishes, every tool has run, or the step budget is used up.
Then transparent rules (risk.py) score each affected component.

Run:  python -m backend.app.orchestrator demo_repo docs\price_paise.diff
"""
import json
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from backend.app.decision_pattern import InvestigationState, decide_next_tool
from backend.app.diff_reader import analyze_diff, read_diff_file
from backend.app.models import Change, Report
from backend.app.risk import QUESTIONS, score_components
from backend.app.tools import build_context, run_tool, tool_descriptions

MAX_STEPS = 5
MAX_NOTE_CHARS = 150
EVIDENCE_LINES_PER_TOOL = 3


@dataclass
class InvestigationResult:
    change: Change
    report: Report
    evidence: list
    tools_run: list
    stop_reason: str

    def to_dict(self):
        return {
            "change": self.change.model_dump(),
            "report": self.report.model_dump(),
            "tools_run": self.tools_run,
            "stop_reason": self.stop_reason,
            "evidence": [e.model_dump() for e in self.evidence],
        }


def run_investigation(diff_text, repo_path=".", scan_dir=".", max_steps=MAX_STEPS,
                      decide=decide_next_tool, on_step=None):
    change = analyze_diff(diff_text, repo_path=repo_path)
    ctx = build_context(repo_path, scan_dir, change)
    descriptions = tool_descriptions()
    state = InvestigationState(
        change_summary=change.change_summary, changed_symbols=list(change.changed_symbols))

    trace, evidence = [], []
    stop_reason = "step budget reached"

    for step in range(1, max_steps + 1):
        state.remaining_steps = max_steps - step + 1
        state.unanswered_questions = [
            q for tool, q in QUESTIONS.items() if tool not in state.tools_run]

        decision = decide(state, descriptions)

        # Guardrail: finishing before any consumer was traced would leave nothing to score.
        if decision.chosen == "finish_analysis" and "trace_consumers" not in state.tools_run:
            decision.chosen = "trace_consumers"
            decision.source = "fallback"
            decision.reason += ("; finish rejected because no consumers were traced yet, "
                                "so trace_consumers runs instead")

        trace.append(decision.to_step(step))
        if on_step:
            on_step(step, max_steps, decision)

        if decision.chosen == "finish_analysis":
            stop_reason = decision.reason
            break

        result = run_tool(decision.chosen, ctx)
        evidence.extend(result.evidence)
        state.tools_run.append(decision.chosen)
        state.evidence_found.append(f"[{decision.chosen}] {result.summary}")
        for item in result.evidence[:EVIDENCE_LINES_PER_TOOL]:
            state.evidence_found.append(
                f"{item.file_path}:{item.line_start} {item.note}"[:MAX_NOTE_CHARS])

    scored = score_components(ctx, state.tools_run, evidence)
    report = Report(
        summary=change.change_summary,
        findings=scored.findings,
        decision_trace=trace,
        missing_tests=scored.missing_tests,
        recommended_tests=scored.recommended_tests,
        open_questions=scored.open_questions,
    )
    return InvestigationResult(change, report, evidence, list(state.tools_run), stop_reason)


def print_step(step, max_steps, decision):
    print(f"step {step}/{max_steps}: {decision.chosen}  "
          f"(confidence {decision.confidence:.2f}, {decision.source})")
    print(f"    {decision.reason}")


def print_run(result):
    print("\n=== Summary ===")
    print(textwrap.fill(result.report.summary, width=100))
    print(f"\ntools run   : {', '.join(result.tools_run) or 'none'}")
    print(f"stopped     : {result.stop_reason}")

    print("\n=== Findings (highest risk first) ===")
    if not result.report.findings:
        print("  none (insufficient evidence)")
    for f in result.report.findings:
        print(f"\n[{f.risk_level.upper()}] {f.component}")
        print(textwrap.fill(f.rationale, width=100, initial_indent="    ", subsequent_indent="    "))
        for e in f.evidence[:3]:
            print(f"      evidence: {e.file_path}:{e.line_start}  ({e.source_tool})")
        print(textwrap.fill("uncertainty: " + f.uncertainty, width=100,
                            initial_indent="    ", subsequent_indent="        "))

    if result.report.missing_tests:
        print("\n=== Missing tests ===")
        for item in result.report.missing_tests:
            print(f"  - {item}")
    if result.report.recommended_tests:
        print("\n=== Recommended tests ===")
        for item in result.report.recommended_tests:
            print(f"  - {item}")
    if result.report.open_questions:
        print("\n=== Open questions ===")
        for item in result.report.open_questions:
            print(f"  - {item}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m backend.app.orchestrator <scan_dir> <diff_file>")
        sys.exit(1)
    scan_dir, diff_file = sys.argv[1], sys.argv[2]
    scan_dir, diff_file = sys.argv[1], sys.argv[2]
    print("Investigating (each Decider call can take several seconds on CPU)...\n")
    outcome = run_investigation(
        read_diff_file(diff_file), repo_path=".", scan_dir=scan_dir, on_step=print_step)
    print_run(outcome)
    out_path = Path("docs") / "last_run.json"
    out_path.write_text(json.dumps(outcome.to_dict(), indent=2), encoding="utf-8")
    print(f"\nSaved full run to {out_path}")
