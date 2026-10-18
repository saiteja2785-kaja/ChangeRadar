"""Part 3: read a Git diff and extract structured facts about the change."""
import ast
import re
import subprocess
import sys
from pathlib import Path

from backend.app.models import Change

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
JSON_KEY_RE = re.compile(r'"(\w+)"\s*:\s*([^,}\s]+)')
DOC_KEY_RE = re.compile(r"^\s*[-*]?\s*(\w+)\s*:\s*(.+)$")
CONTRACT_EXTENSIONS = (".md", ".json", ".yaml", ".yml", ".proto", ".graphql")
DOC_EXTENSIONS = (".md", ".yaml", ".yml")


def read_diff_file(path):
    return Path(path).read_text(encoding="utf-8")


def git_diff(repo_path, base, head):
    result = subprocess.run(
        ["git", "diff", base, head],
        cwd=repo_path, capture_output=True, text=True,
        encoding="utf-8", check=True,
    )
    return result.stdout


def parse_diff(diff_text):
    """Split a unified diff into per-file changes."""
    files = []
    current = None
    in_hunk = False
    new_line = 0
    removed_block = []
    added_block = []

    def flush_block():
        nonlocal removed_block, added_block
        if current is not None:
            for old, new in zip(removed_block, added_block):
                current["pairs"].append((old, new))
        removed_block = []
        added_block = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            flush_block()
            in_hunk = False
            current = {"path": line.rsplit(" b/", 1)[-1], "added": [], "pairs": []}
            files.append(current)
        elif current is None:
            continue
        elif line.startswith("@@"):
            flush_block()
            in_hunk = True
            match = HUNK_RE.match(line)
            if match:
                new_line = int(match.group(2))
        elif not in_hunk or line.startswith("\\"):
            continue
        elif line.startswith("+"):
            current["added"].append((new_line, line[1:]))
            added_block.append(line[1:])
            new_line += 1
        elif line.startswith("-"):
            removed_block.append(line[1:])
        else:
            flush_block()
            new_line += 1
    flush_block()
    return files


def is_test_file(path):
    p = Path(path)
    return "tests" in p.parts or p.name.lower().startswith("test_")


def is_contract_file(path):
    lower = path.lower()
    return lower.endswith(CONTRACT_EXTENSIONS) or "schema" in lower or "contract" in lower


def find_changed_fields(path, pairs):
    """Return (field, old_text, new_text) for fields whose value changed."""
    found = []
    for old, new in pairs:
        old_vals = dict(JSON_KEY_RE.findall(old))
        for key, value in JSON_KEY_RE.findall(new):
            if key in old_vals and old_vals[key] != value:
                found.append((key, old_vals[key], value))
        if path.endswith(DOC_EXTENSIONS):
            m_old, m_new = DOC_KEY_RE.match(old), DOC_KEY_RE.match(new)
            if m_old and m_new and m_old.group(1) == m_new.group(1) \
                    and m_old.group(2) != m_new.group(2):
                found.append((m_old.group(1), m_old.group(2), m_new.group(2)))
    return found


def find_changed_functions(path, added_lines, repo_path):
    """Use AST to find functions/classes that contain changed lines."""
    file_path = Path(repo_path) / path
    if not path.endswith(".py") or not file_path.exists():
        return []
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    changed = {n for n, _ in added_lines}
    names = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if any(node.lineno <= n <= node.end_lineno for n in changed):
                names.append(node.name)
    return names


def short(text, limit=80):
    return text if len(text) <= limit else text[:limit] + "..."


def analyze_diff(diff_text, repo_path="."):
    files = parse_diff(diff_text)
    changed_files, symbols, contract_files, tests, details = [], [], [], [], []

    for f in files:
        path = f["path"]
        changed_files.append(path)
        functions = find_changed_functions(path, f["added"], repo_path)

        if is_test_file(path):
            if functions:
                tests.extend(f"{path}::{name}" for name in functions)
            else:
                tests.append(path)
            continue

        if is_contract_file(path):
            contract_files.append(path)
        for name in functions:
            if name not in symbols:
                symbols.append(name)
        for key, old, new in find_changed_fields(path, f["pairs"]):
            if key not in symbols:
                symbols.append(key)
            details.append(f"{key}: {short(old)} -> {short(new)}")

    parts = [f"{len(changed_files)} file(s) changed: {', '.join(changed_files)}."]
    if symbols:
        parts.append(f"Changed symbols/fields: {', '.join(symbols)}.")
    for d in details[:4]:
        parts.append(f"Value change: {d}")
    if contract_files:
        parts.append(f"Contract files changed: {', '.join(contract_files)}.")
    if tests:
        parts.append(f"Tests touched: {', '.join(tests)}.")

    return Change(
        changed_files=changed_files,
        changed_symbols=symbols,
        changed_contract_files=contract_files,
        change_summary=" ".join(parts),
        touched_tests=tests,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.app.diff_reader <diff_file>")
        sys.exit(1)
    print(analyze_diff(read_diff_file(sys.argv[1])).model_dump_json(indent=2))
