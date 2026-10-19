from pathlib import Path

from backend.app.graph_builder import build_graph, find_impact

ROOT = Path(__file__).resolve().parents[1]


def test_price_impact():
    G = build_graph(ROOT, "demo_repo")
    impact = find_impact(G, "price")
    direct = {c["label"] for c in impact["direct"]}
    indirect = {c["label"] for c in impact["indirect"]}
    tests = {t["label"] for t in impact["tests"]}

    assert any(x.endswith("invoice.py::calculate_total") for x in direct)
    assert any(x.endswith("invoice.py::format_invoice_line") for x in direct)
    assert any(x.endswith("checkout.py::checkout_summary") for x in direct)
    assert any(x.endswith("schema.md") for x in direct)
    assert any(x.endswith("checkout.py::shipping_fee") for x in indirect)
    assert any(x.endswith("test_checkout.py::test_empty_cart_pays_shipping") for x in tests)


def test_unknown_symbol_gives_no_evidence():
    G = build_graph(ROOT, "demo_repo")
    assert find_impact(G, "does_not_exist")["found"] is False
