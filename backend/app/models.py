from pydantic import BaseModel, Field
from typing import Optional


class Change(BaseModel):
    changed_files: list[str] = []
    changed_symbols: list[str] = []
    changed_contract_files: list[str] = []
    change_summary: str = ""
    touched_tests: list[str] = []


class Evidence(BaseModel):
    source_tool: str
    file_path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    excerpt: str = ""
    note: str = ""


class Finding(BaseModel):
    component: str
    risk_level: str = "unknown"  # low / medium / high / unknown
    rationale: str = ""
    evidence: list[Evidence] = []
    uncertainty: str = ""
    insufficient_evidence: bool = False


class DecisionStep(BaseModel):
    step: int
    options: list[str]
    chosen: str
    confidence: float
    fallback_used: bool = False
    probabilities: dict[str, float] = {}
    reason: str = ""
    latency_ms: Optional[float] = None


class Report(BaseModel):
    summary: str = ""
    findings: list[Finding] = []
    decision_trace: list[DecisionStep] = []
    missing_tests: list[str] = []
    recommended_tests: list[str] = []
    open_questions: list[str] = []
