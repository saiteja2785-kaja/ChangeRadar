"""Part 5: investigation tools. Each tool returns real evidence from the repo."""
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from backend.app.diff_reader import analyze_diff, read_diff_file
from backend.app.graph_builder import build_graph, file_id, find_impact, func_id, symbol_id, test_id
from backend.app.models import Change, Evidence


@dataclass
class ToolContext:
    root: Path
    graph: object
    change: Change


@dataclass
class ToolResult:
    tool: str
    evidence: list = field(default_factory=list)
    summary: str = ""


@dataclass
class Tool:
    name: str
    description: str
    run: Callable


def build_context(repo_path, scan_dir, change):
    root = Path(repo_path).resolve()
    return ToolContext(root=root, graph=build_graph(root, scan_dir), change=change)


# ---------- helpers ----------

def read_block(root, path, start, end):
    file_path = root / path
    if not file_path.exists():
        return ""
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(lines[max(start - 1, 0):end])


def read_excerpt(root, path, start, end, max_lines=6):
    capped_end = min(end, start - 1 + max_lines)
    return textwrap.dedent(read_block(root, path, start, capped_end)).strip()


def make_evidence(ctx, tool, path, start, end, note):
    return Evidence(
        source_tool=tool, file_path=path, line_start=start, line_end=end,
        excerpt=read_excerpt(ctx.root, path, start, end), note=note,
    )


def node_for_label(label):
    if "::" in label:
        path, name = label.split("::", 1)
        return func_id(path, name)
    return file_id(label)


def impacts(ctx):
    return [find_impact(ctx.graph, s) for s in ctx.change.changed_symbols]


def consumer_nodes(ctx):
    """Functions/files outside the changed files that use the field, directly or indirectly.
    Returns {node_id: (symbol, depth, via_node)}."""
    changed = set(ctx.change.changed_files)
    found = {}
    for impact in impacts(ctx):
        for c in impact["direct"]:
            if c["type"] in ("function", "file") and c["label"].split("::")[0] not in changed:
                found.setdefault(node_for_label(c["label"]), (impact["symbol"], 0, None))
        for c in impact["indirect"]:
            if c["label"].split("::")[0] not in changed:
                found.setdefault(
                    node_for_label(c["label"]),
                    (impact["symbol"], c["depth"], node_for_label(c["via"])),
                )
    return found


# ---------- the five tools ----------

def trace_consumers(ctx):
    G = ctx.graph
    consumers = consumer_nodes(ctx)
    evidence, seen = [], set()
    for node, (symbol, depth, via) in sorted(consumers.items()):
        data = G.nodes[node]
        name = data.get("name")
        if depth == 0:
            lines = sorted({
                d["line"] for _, target, d in G.out_edges(node, data=True)
                if target == symbol_id(symbol) and d.get("type") == "references"
            })
            note = f"{name} reads the changed field '{symbol}' directly"
        else:
            lines = sorted({
                d["line"] for d in (G.get_edge_data(node, via) or {}).values()
                if d.get("type") == "calls"
            })
            via_name = G.nodes[via].get("name")
            note = f"{name} calls {via_name}, which uses '{symbol}' (indirect, depth {depth})"
        for line in lines:
            key = (data["path"], line)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(make_evidence(ctx, "trace_consumers", data["path"], line, line, note))
    if consumers:
        summary = f"Found {len(consumers)} consumer component(s) outside the changed files."
    else:
        summary = "No consumers found in the scanned code (insufficient evidence)."
    return ToolResult("trace_consumers", evidence, summary)


def inspect_contract(ctx):
    G = ctx.graph
    paths = set(ctx.change.changed_contract_files)
    for symbol in ctx.change.changed_symbols:
        target = symbol_id(symbol)
        if target in G:
            for u, _, d in G.in_edges(target, data=True):
                if d.get("type") == "references" and G.nodes[u].get("type") == "schema":
                    paths.add(G.nodes[u]["path"])
    evidence = []
    for path in sorted(paths):
        file_path = ctx.root / path
        if not file_path.exists():
            continue
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for symbol in ctx.change.changed_symbols:
            pattern = re.compile(rf"\b{re.escape(symbol)}\b")
            for number, text in enumerate(lines, start=1):
                if pattern.search(text):
                    note = f"Contract documents '{symbol}'"
                    if path in ctx.change.changed_contract_files:
                        note += " (this contract file was changed in the diff)"
                    evidence.append(make_evidence(ctx, "inspect_contract", path, number, number, note))
    if evidence:
        summary = f"Read {len(paths)} contract/schema file(s) that mention the changed field."
    else:
        summary = "No contract or schema file found for the changed field (insufficient evidence)."
    return ToolResult("inspect_contract", evidence, summary)


def find_related_tests(ctx):
    G = ctx.graph
    tests = {}
    for impact in impacts(ctx):
        for t in impact["tests"]:
            tests.setdefault(t["label"], t["reason"])
    for label in ctx.change.touched_tests:
        tests.setdefault(label, "modified in this change")

    symbols = ctx.change.changed_symbols
    quoted = ", ".join(repr(s) for s in symbols)
    evidence = []
    for label, reason in sorted(tests.items()):
        if "::" not in label:
            continue
        path, name = label.split("::", 1)
        node = test_id(path, name)
        if node not in G:
            continue
        data = G.nodes[node]
        body = read_block(ctx.root, path, data["line_start"], data["line_end"])
        mentioned = [s for s in symbols if re.search(rf"\b{re.escape(s)}\b", body)]
        if mentioned:
            note = (f"{name} ({reason}) references {', '.join(repr(s) for s in mentioned)}; "
                    f"confirm it checks the new convention")
        else:
            note = (f"{name} ({reason}) never mentions {quoted}; "
                    f"the changed convention is likely untested here")
        evidence.append(make_evidence(
            ctx, "find_related_tests", path, data["line_start"], data["line_end"], note))

    missing = 0
    for node in sorted(consumer_nodes(ctx)):
        data = G.nodes[node]
        if data.get("type") != "function":
            continue
        has_test = any(d.get("type") == "tested_by" for _, _, d in G.out_edges(node, data=True))
        if not has_test:
            missing += 1
            evidence.append(make_evidence(
                ctx, "find_related_tests", data["path"], data["line_start"], data["line_end"],
                f"No test calls {data['name']} directly, but it is affected by the change"))

    summary = f"{len(tests)} related test(s); {missing} affected component(s) with no direct test."
    return ToolResult("find_related_tests", evidence, summary)


def inspect_callers(ctx):
    G = ctx.graph
    changed_files = set(ctx.change.changed_files)
    producers = set()
    for impact in impacts(ctx):
        for c in impact["direct"]:
            if c["type"] == "function" and c["label"].split("::")[0] in changed_files:
                producers.add(node_for_label(c["label"]))
    for node, data in G.nodes(data=True):
        if data.get("type") == "function" and data.get("name") in ctx.change.changed_symbols:
            producers.add(node)

    evidence, seen = [], set()
    for producer in sorted(producers):
        producer_name = G.nodes[producer].get("name")
        for caller, _, d in G.in_edges(producer, data=True):
            if d.get("type") != "calls" or G.nodes[caller].get("type") != "function":
                continue
            data = G.nodes[caller]
            key = (data["path"], d["line"])
            if key in seen:
                continue
            seen.add(key)
            evidence.append(make_evidence(
                ctx, "inspect_callers", data["path"], d["line"], d["line"],
                f"{data['name']} calls {producer_name}, which is changed or reads a changed field; "
                f"check how it interprets the returned value"))
    if evidence:
        summary = f"Found {len(evidence)} call site(s) of changed code."
    else:
        summary = "No callers of the changed code found (insufficient evidence)."
    return ToolResult("inspect_callers", evidence, summary)


def finish_analysis(ctx):
    return ToolResult("finish_analysis", [], "Investigation finished.")


# ---------- registry ----------

TOOLS = {
    "trace_consumers": Tool(
        "trace_consumers",
        "Find components that read the changed field or call code that does (direct and indirect consumers).",
        trace_consumers),
    "inspect_contract": Tool(
        "inspect_contract",
        "Read the API contract or schema files that document the changed field.",
        inspect_contract),
    "find_related_tests": Tool(
        "find_related_tests",
        "Find tests related to the affected components, tests that never mention the field, and untested components.",
        find_related_tests),
    "inspect_callers": Tool(
        "inspect_callers",
        "Inspect the call sites of the changed code to see how callers use its output.",
        inspect_callers),
    "finish_analysis": Tool(
        "finish_analysis",
        "Stop investigating because enough evidence has been gathered.",
        finish_analysis),
}


def tool_descriptions():
    return {name: tool.description for name, tool in TOOLS.items()}


def run_tool(name, ctx):
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    return TOOLS[name].run(ctx)


def print_result(result):
    print(f"\n=== {result.tool} ===")
    print(result.summary)
    for e in result.evidence:
        span = f"{e.line_start}" if e.line_start == e.line_end else f"{e.line_start}-{e.line_end}"
        print(f"  {e.file_path}:{span}")
        for row in e.excerpt.splitlines()[:3]:
            print(f"      | {row}")
        print(f"      -> {e.note}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m backend.app.tools <scan_dir> <diff_file>")
        sys.exit(1)
    change = analyze_diff(read_diff_file(sys.argv[2]), repo_path=".")
    context = build_context(".", sys.argv[1], change)
    for tool_name in TOOLS:
        print_result(run_tool(tool_name, context))
