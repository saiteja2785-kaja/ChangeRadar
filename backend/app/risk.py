"""
Part 7: transparent, rule-based risk scoring. No LLM is asked for a number.

Score = sum of factors. A factor only counts if the evidence for it was collected.
  dependency   direct +3 | indirect 1 hop +2 | indirect 2+ hops +1
  contract     +2 the contract changed in this diff but the component was not part of the change
               (needs inspect_contract)
  handling     +2 no sign in its code that it adapts to the change | -2 it mentions unit conversion
  calculation  +3 it does arithmetic or comparisons | 0 it only passes data through
  tests        +2 no test calls it | +1 tests exist but never mention the changed field
               | 0 a test mentions it (needs find_related_tests)
  callers      +1 other functions call it, so a wrong value propagates (needs inspect_callers)
Levels: high >= 10, medium >= 5, low below 5.
The result is a risk estimate from static analysis, not proof that anything fails at runtime.
"""
import ast
import re
import textwrap
from dataclasses import dataclass, field

from backend.app.graph_builder import label as node_label
from backend.app.models import Finding
from backend.app.tools import consumer_nodes, read_block

HIGH_AT = 10
MEDIUM_AT = 5
MAX_EVIDENCE_PER_FINDING = 8
MAX_COMPONENT_QUESTIONS = 5

QUESTIONS = {
    "trace_consumers": "Which components read or depend on the changed field?",
    "inspect_contract": "Does the API contract document the new convention?",
    "find_related_tests": "Do existing tests cover the changed behavior?",
    "inspect_callers": "How do callers use the output of the changed code?",
}

NAME_HINT_RE = re.compile(
    r"(^|_)(paise|paisa|rupees?|cents?|convert\w*|minor_unit\w*)(_|$)", re.IGNORECASE)


@dataclass
class Factor:
    name: str
    points: int
    detail: str


@dataclass
class ComponentScore:
    node: str
    label: str
    name: str
    score: int
    factors: list
    tests: list
    tests_known: bool
    tests_mention_field: bool
    adapts: bool


@dataclass
class ScoreResult:
    findings: list = field(default_factory=list)
    missing_tests: list = field(default_factory=list)
    recommended_tests: list = field(default_factory=list)
    open_questions: list = field(default_factory=list)


def level_for(score):
    if score >= HIGH_AT:
        return "high"
    if score >= MEDIUM_AT:
        return "medium"
    return "low"


def parse(source):
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def has_unit_handling(source):
    """True if the code (not docstrings or strings) shows unit-conversion handling."""
    tree = parse(source)
    if tree is None:
        return False
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        if any(NAME_HINT_RE.search(n) for n in names):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mult)):
            if any(isinstance(side, ast.Constant) and side.value == 100
                   for side in (node.left, node.right)):
                return True
    return False


def has_calculation(source):
    """True if the code does arithmetic or comparisons (not just passing data through)."""
    tree = parse(source)
    if tree is None:
        return False
    return any(isinstance(n, (ast.BinOp, ast.AugAssign, ast.Compare)) for n in ast.walk(tree))


def component_source(ctx, node):
    data = ctx.graph.nodes[node]
    if data.get("type") == "function":
        return textwrap.dedent(
            read_block(ctx.root, data["path"], data["line_start"], data["line_end"]))
    return read_block(ctx.root, data["path"], 1, 100000)


def assess(ctx, node, depth, tools_run):
    G = ctx.graph
    symbols = ctx.change.changed_symbols
    source = component_source(ctx, node)
    factors = []

    if depth == 0:
        factors.append(Factor("dependency", 3, "reads the changed field directly"))
    elif depth == 1:
        factors.append(Factor("dependency", 2, "calls code that reads the changed field (1 hop)"))
    else:
        factors.append(Factor("dependency", 1, f"indirect dependency ({depth} hops)"))

    if "inspect_contract" in tools_run:
        if ctx.change.changed_contract_files:
            factors.append(Factor(
                "contract", 2,
                "the contract changed in this diff but this component was not part of the change"))
        else:
            factors.append(Factor("contract", 0, "no contract change found in the diff"))

    adapts = has_unit_handling(source)
    if adapts:
        factors.append(Factor(
            "handling", -2, "its code mentions unit conversion, so it may already adapt (verify)"))
    else:
        factors.append(Factor("handling", 2, "no sign in its code that it adapts to the change"))

    if has_calculation(source):
        factors.append(Factor(
            "calculation", 3, "does arithmetic or comparisons, so a wrong value changes results"))
    else:
        factors.append(Factor("calculation", 0, "only passes data through (no arithmetic or comparison)"))

    tests = []
    tests_known = "find_related_tests" in tools_run
    mentions = False
    if tests_known:
        tests = list(dict.fromkeys(
            v for _, v, d in G.out_edges(node, data=True) if d.get("type") == "tested_by"))
        for t in tests:
            td = G.nodes[t]
            body = read_block(ctx.root, td["path"], td["line_start"], td["line_end"])
            if any(re.search(rf"\b{re.escape(s)}\b", body) for s in symbols):
                mentions = True
        if not tests:
            factors.append(Factor("tests", 2, "no test calls it directly"))
        elif mentions:
            factors.append(Factor(
                "tests", 0, "a test references the changed field (confirm it checks the new convention)"))
        else:
            factors.append(Factor("tests", 1, "tests call it but never mention the changed field"))

    if "inspect_callers" in tools_run:
        callers = {u for u, _, d in G.in_edges(node, data=True)
                   if d.get("type") == "calls" and G.nodes[u].get("type") == "function"}
        if callers:
            factors.append(Factor(
                "callers", 1, f"called by {len(callers)} other function(s), so a wrong value propagates"))
        else:
            factors.append(Factor("callers", 0, "no other function calls it"))

    return ComponentScore(
        node=node, label=node_label(G, node), name=G.nodes[node].get("name", node),
        score=sum(f.points for f in factors), factors=factors, tests=tests,
        tests_known=tests_known, tests_mention_field=mentions, adapts=adapts)


def evidence_for(ctx, comp, evidence):
    G = ctx.graph
    data = G.nodes[comp.node]
    test_spots = {(G.nodes[t]["path"], G.nodes[t]["line_start"]) for t in comp.tests}
    picked, seen = [], set()
    for e in evidence:
        in_component = e.file_path == data["path"] and (
            data.get("type") != "function"
            or (e.line_start is not None and data["line_start"] <= e.line_start <= data["line_end"]))
        is_test = (e.file_path, e.line_start) in test_spots
        is_contract = e.source_tool == "inspect_contract"
        if not (in_component or is_test or is_contract):
            continue
        key = (e.source_tool, e.file_path, e.line_start, e.note)
        if key in seen:
            continue
        seen.add(key)
        picked.append(e)
    return picked[:MAX_EVIDENCE_PER_FINDING]


def rationale_for(comp, level):
    parts = "; ".join(f"{f.name} {f.points:+d} ({f.detail})" for f in comp.factors)
    return f"Risk score {comp.score} -> {level} (high >= {HIGH_AT}, medium >= {MEDIUM_AT}). {parts}."


def score_components(ctx, tools_run, evidence):
    """Turn collected evidence into scored findings, missing tests and open questions."""
    result = ScoreResult()
    symbols = ", ".join(ctx.change.changed_symbols) or "the changed code"
    optional = ("inspect_contract", "find_related_tests", "inspect_callers")
    unchecked = [t for t in optional if t not in tools_run]
    base_questions = [QUESTIONS[t] for t in unchecked]

    if "trace_consumers" not in tools_run:
        result.open_questions = [QUESTIONS["trace_consumers"]] + base_questions
        return result

    consumers = consumer_nodes(ctx)
    if not consumers:
        result.open_questions = [
            f"No component outside the changed files was found that uses {symbols} "
            f"(insufficient evidence)."] + base_questions
        return result

    components = [assess(ctx, node, depth, tools_run) for node, (_, depth, _) in consumers.items()]
    components.sort(key=lambda c: (-c.score, c.label))

    if unchecked:
        uncertainty = "Not checked: " + "; ".join(QUESTIONS[t] for t in unchecked) + " "
    else:
        uncertainty = ""
    uncertainty += "This is a static estimate from code structure, not proof of a runtime failure."
    insufficient = not any(t in tools_run for t in optional)

    component_questions = []
    for comp in components:
        level = level_for(comp.score)
        result.findings.append(Finding(
            component=comp.label, risk_level=level, rationale=rationale_for(comp, level),
            evidence=evidence_for(ctx, comp, evidence), uncertainty=uncertainty,
            insufficient_evidence=insufficient))

        if comp.tests_known and not comp.tests:
            result.missing_tests.append(f"{comp.label}: no test calls it directly")
        if level in ("high", "medium"):
            if comp.tests_known and not comp.tests:
                result.recommended_tests.append(
                    f"Add a test for {comp.name}: use the new value convention for {symbols} "
                    f"and assert the expected result.")
            elif comp.tests_known and not comp.tests_mention_field:
                names = ", ".join(ctx.graph.nodes[t]["name"] for t in comp.tests)
                result.recommended_tests.append(
                    f"Extend {names} to cover the new value convention for {symbols}.")
            else:
                result.recommended_tests.append(
                    f"Add or confirm a regression test for {comp.name} under the new convention "
                    f"for {symbols}.")
            if not comp.adapts and len(component_questions) < MAX_COMPONENT_QUESTIONS:
                component_questions.append(
                    f"Does {comp.name} convert to the new value convention? "
                    f"No conversion was found in its code.")

    result.open_questions = (
        base_questions + component_questions
        + ["Dynamic access and code in other languages are not visible to this static analysis."])
    return result
