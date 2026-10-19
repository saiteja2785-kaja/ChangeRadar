"""Part 4: build a dependency graph of a repository and query the impact of a field."""
import ast
import json
import re
import sys
from collections import deque
from pathlib import Path

import networkx as nx

SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", ".next", ".pytest_cache"}
DOC_EXTENSIONS = (".md", ".yaml", ".yml")
DOC_KEY_RE = re.compile(r"^\s*[-*]?\s*(\w+)\s*:")


def file_id(path):
    return f"file:{path}"


def func_id(path, name):
    return f"func:{path}::{name}"


def test_id(path, name):
    return f"test:{path}::{name}"


def symbol_id(name):
    return f"symbol:{name}"


def is_test_path(path):
    p = Path(path)
    return "tests" in p.parts or p.name.lower().startswith("test_")


def iter_files(root, scan_dir, extensions):
    base = root / scan_dir
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix not in extensions:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def build_module_map(root, py_files):
    """Map dotted module names (demo_repo.api.products) to file paths."""
    modules = {}
    for p in py_files:
        rel = p.relative_to(root)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules[".".join(parts)] = rel.as_posix()
    return modules


def field_refs(node, call_attrs):
    """Return (name, line) pairs for field-like references in one AST node."""
    refs = []
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            refs.append((key.value, node.lineno))
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                refs.append((key.value, key.lineno))
    elif isinstance(node, ast.Attribute) and id(node) not in call_attrs:
        refs.append((node.attr, node.lineno))
    return refs


def resolve_call(name, funcs, imported, parsed):
    if name in funcs:
        return funcs[name]
    if name in imported:
        target, original = imported[name]
        return parsed[target][1].get(original)
    return None


def add_reference(G, source, name, line):
    G.add_node(symbol_id(name), type="symbol", name=name)
    G.add_edge(source, symbol_id(name), type="references", line=line)


def build_graph(repo_path=".", scan_dir="."):
    root = Path(repo_path).resolve()
    py_files = list(iter_files(root, scan_dir, (".py",)))
    doc_files = list(iter_files(root, scan_dir, DOC_EXTENSIONS))
    modules = build_module_map(root, py_files)
    G = nx.MultiDiGraph()
    parsed = {}

    # Pass 1: file, function and test nodes
    for p in py_files:
        rel = p.relative_to(root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        G.add_node(file_id(rel), type="file", path=rel, name=Path(rel).name)
        funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_test = is_test_path(rel) and node.name.startswith("test_")
                nid = test_id(rel, node.name) if is_test else func_id(rel, node.name)
                funcs[node.name] = nid
                G.add_node(
                    nid, type="test" if is_test else "function", path=rel,
                    name=node.name, line_start=node.lineno, line_end=node.end_lineno,
                )
                G.add_edge(nid, file_id(rel), type="defined_in")
        parsed[rel] = (tree, funcs)

    # Pass 2: imports, calls, field references
    for rel, (tree, funcs) in parsed.items():
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                target = modules.get(node.module)
                if target in parsed:
                    G.add_edge(file_id(rel), file_id(target), type="imports", line=node.lineno)
                    for alias in node.names:
                        imported[alias.asname or alias.name] = (target, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    target = modules.get(alias.name)
                    if target in parsed:
                        G.add_edge(file_id(rel), file_id(target), type="imports", line=node.lineno)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            source = funcs[node.name]
            call_attrs = {id(c.func) for c in ast.walk(node) if isinstance(c, ast.Call)}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    target = resolve_call(sub.func.id, funcs, imported, parsed)
                    if target and target != source:
                        G.add_edge(source, target, type="calls", line=sub.lineno)
                for name, line in field_refs(sub, call_attrs):
                    add_reference(G, source, name, line)

        # module-level code (outside functions and classes)
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            call_attrs = {id(c.func) for c in ast.walk(stmt) if isinstance(c, ast.Call)}
            for sub in ast.walk(stmt):
                for name, line in field_refs(sub, call_attrs):
                    add_reference(G, file_id(rel), name, line)

    # Docs and schema files: lines like "- price: integer ..."
    for p in doc_files:
        rel = p.relative_to(root).as_posix()
        lower = rel.lower()
        kind = "schema" if ("schema" in lower or "contract" in lower) else "document"
        G.add_node(file_id(rel), type=kind, path=rel, name=Path(rel).name)
        text = p.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), start=1):
            match = DOC_KEY_RE.match(line)
            if match:
                add_reference(G, file_id(rel), match.group(1), number)

    # tested_by: reverse of test -> function calls
    calls_from_tests = [
        (u, v) for u, v, d in G.edges(data=True)
        if d.get("type") == "calls" and G.nodes[u].get("type") == "test"
    ]
    for test, func in calls_from_tests:
        G.add_edge(func, test, type="tested_by")

    return G


def label(G, node):
    data = G.nodes[node]
    if data.get("type") in ("function", "test"):
        return f"{data['path']}::{data['name']}"
    return data.get("path") or data.get("name") or node


def find_impact(G, symbol):
    """Who references this field, who calls that code, and which tests touch it."""
    target = symbol_id(symbol)
    result = {"symbol": symbol, "found": target in G, "direct": [], "indirect": [], "tests": []}
    if target not in G:
        return result

    direct_lines = {}
    for u, _, d in G.in_edges(target, data=True):
        if d.get("type") == "references":
            direct_lines.setdefault(u, set()).add(d.get("line"))

    tests = {}
    for node, lines in sorted(direct_lines.items()):
        node_type = G.nodes[node].get("type")
        if node_type == "test":
            tests[node] = "references the field"
        else:
            result["direct"].append(
                {"label": label(G, node), "type": node_type, "lines": sorted(lines)}
            )

    seen = set(direct_lines)
    queue = deque((n, 1) for n in sorted(direct_lines) if G.nodes[n].get("type") == "function")
    while queue:
        node, depth = queue.popleft()
        for caller, _, d in G.in_edges(node, data=True):
            if d.get("type") != "calls" or caller in seen:
                continue
            seen.add(caller)
            if G.nodes[caller].get("type") == "test":
                tests[caller] = f"calls {G.nodes[node]['name']}"
            else:
                result["indirect"].append(
                    {"label": label(G, caller), "depth": depth, "via": label(G, node)}
                )
                queue.append((caller, depth + 1))

    result["tests"] = [{"label": label(G, n), "reason": r} for n, r in sorted(tests.items())]
    return result


def export_graph(G, out_path):
    data = {
        "nodes": [{"id": n, **attrs} for n, attrs in G.nodes(data=True)],
        "edges": [{"source": u, "target": v, **attrs} for u, v, attrs in G.edges(data=True)],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")


def print_impact(impact):
    print(f"\nImpact of changing '{impact['symbol']}'")
    if not impact["found"]:
        print("  Not found in the graph (insufficient evidence).")
        return
    print("\nDirect (reference the field):")
    for c in impact["direct"]:
        print(f"  [{c['type']}] {c['label']}  lines {c['lines']}")
    print("\nIndirect (call code that uses the field):")
    for c in impact["indirect"]:
        print(f"  {c['label']}  (depth {c['depth']}, via {c['via']})")
    print("\nTests that touch these components:")
    for t in impact["tests"]:
        print(f"  {t['label']}  ({t['reason']})")


if __name__ == "__main__":
    scan_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    symbol = sys.argv[2] if len(sys.argv) > 2 else None
    graph = build_graph(".", scan_dir)
    export_graph(graph, "docs/dependency_graph.json")
    print(f"Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges "
          f"(saved to docs/dependency_graph.json)")
    if symbol:
        print_impact(find_impact(graph, symbol))
