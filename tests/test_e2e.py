"""End-to-end tests for ChangeRadar (Part 10).

Fill in the TODO adapter below so it calls your real pipeline (Parts 3-8).
Tests assert on properties of the result, not on hardcoded answers.
"""
import json, shutil
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_REPO = ROOT / "demo_repo"


def run_pipeline(repo_path: Path, diff_path: Path | None = None) -> dict:
    """TODO: call your orchestrator + report generator and return the run as a dict with keys:
    findings (list), decision_trace (list), report (dict).
    Example: from backend.orchestrator import run_analysis; return run_analysis(repo_path, diff_path).model_dump()
    """
    raise NotImplementedError("Wire this to your pipeline")


@pytest.fixture(scope="module")
def demo_run():
    return run_pipeline(DEMO_REPO)


def test_trace_has_real_decisions(demo_run):
    trace = demo_run["decision_trace"]
    assert 1 <= len(trace) <= 8, "step budget respected"
    for step in trace:
        assert step["choice"] in {"trace_consumers", "inspect_contract", "find_related_tests",
                                  "inspect_callers", "finish_analysis"}
        assert 0.0 <= step["confidence"] <= 1.0


def test_findings_have_evidence(demo_run):
    for f in demo_run["findings"]:
        assert f["evidence"] or f["risk_level"] == "insufficient evidence"
        for e in f["evidence"]:
            assert e["file_path"] and e["line_start"] >= 1


def test_invoice_service_is_high_risk(demo_run):
    inv = [f for f in demo_run["findings"] if "invoice" in f["component"].lower()]
    assert inv and inv[0]["risk_level"].lower() == "high"


def test_checkout_tests_flagged_as_gap(demo_run):
    text = json.dumps(demo_run["findings"]).lower()
    assert "checkout" in text and ("gap" in text or "no test" in text or "missing" in text)


def test_report_recommends_unit_regression_test(demo_run):
    text = json.dumps(demo_run["report"])
    assert "500" in text and "50000" in text


def test_report_claims_map_to_evidence(demo_run):
    # TODO: if you implemented the claim check in Part 8, call it here and assert no unmapped claims.
    assert demo_run["report"]


def test_renamed_function_scenario(tmp_path):
    """Extra scenario: rename a function used by another module; consumers must still be found."""
    repo = tmp_path / "demo_repo"
    shutil.copytree(DEMO_REPO, repo)
    # TODO: pick a real function name from your demo repo and rename it (definition + one caller left stale).
    pytest.skip("Set OLD_NAME/NEW_NAME for your demo repo, then remove this skip")
    # old, new = "OLD_NAME", "NEW_NAME"
    # target = repo / "api" / "..."
    # target.write_text(target.read_text().replace(old, new))
    # run = run_pipeline(repo)
    # assert any(old in json.dumps(f) for f in run["findings"])


def test_fallback_on_invalid_decider_output():
    # TODO: import your decider module and call it with a stub that returns an invalid option;
    # assert fallback_used is True and the chosen option is in the allowed set.
    pytest.skip("Wire to your Part 6 module (stubbing the model call is fine in a unit test)")
