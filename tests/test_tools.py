from pathlib import Path

import pytest

from backend.app.diff_reader import analyze_diff, read_diff_file
from backend.app.tools import TOOLS, build_context, run_tool, tool_descriptions

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ctx():
    change = analyze_diff(read_diff_file(ROOT / "docs" / "price_paise.diff"), repo_path=ROOT)
    return build_context(ROOT, "demo_repo", change)


def test_trace_consumers(ctx):
    result = run_tool("trace_consumers", ctx)
    paths = {e.file_path for e in result.evidence}
    notes = " ".join(e.note for e in result.evidence)
    assert any(p.endswith("invoice.py") for p in paths)
    assert any(p.endswith("checkout.py") for p in paths)
    assert not any(p.endswith("products.py") for p in paths)
    assert "shipping_fee" in notes
    assert all(e.excerpt for e in result.evidence)


def test_inspect_contract(ctx):
    result = run_tool("inspect_contract", ctx)
    assert any(e.file_path.endswith("schema.md") for e in result.evidence)
    assert any("paise" in e.excerpt.lower() for e in result.evidence)


def test_find_related_tests(ctx):
    notes = " ".join(e.note for e in run_tool("find_related_tests", ctx).evidence)
    assert "likely untested" in notes
    assert "No test calls format_invoice_line" in notes


def test_inspect_callers(ctx):
    result = run_tool("inspect_callers", ctx)
    assert any("get_product(" in e.excerpt for e in result.evidence)


def test_finish_and_registry(ctx):
    assert run_tool("finish_analysis", ctx).evidence == []
    assert set(tool_descriptions()) == set(TOOLS)
    with pytest.raises(ValueError):
        run_tool("not_a_tool", ctx)
