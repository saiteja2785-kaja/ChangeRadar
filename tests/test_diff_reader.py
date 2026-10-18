from pathlib import Path

from backend.app.diff_reader import analyze_diff, read_diff_file

ROOT = Path(__file__).resolve().parents[1]


def test_demo_diff():
    change = analyze_diff(read_diff_file(ROOT / "docs" / "price_paise.diff"), repo_path=ROOT)
    assert "price" in change.changed_symbols
    assert "demo_repo/api/schema.md" in change.changed_contract_files
    assert any("test_api" in t for t in change.touched_tests)
    assert not any("invoice" in f for f in change.changed_files)
