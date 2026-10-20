# Architecture

```mermaid
flowchart LR
    UI[Next.js UI] -->|submit diff / sample repo| API[FastAPI]
    API --> DIFF[Diff reader\nPython AST]
    API --> GRAPH[Graph builder\nNetworkX]
    DIFF --> ORCH
    GRAPH --> ORCH
    subgraph Loop[Investigation loop - step budget 5 to 8]
      ORCH[Orchestrator] -->|state + allowed options| DEC[Decider 2B module]
      DEC -->|choice + confidence| ORCH
      ORCH --> TOOLS[Tools:\ntrace_consumers\ninspect_contract\nfind_related_tests\ninspect_callers\nfinish_analysis]
      TOOLS -->|Evidence items| ORCH
    end
    ORCH --> RISK[Rule-based risk scoring]
    RISK --> REP[Bedrock report writer\n+ claim-to-evidence check]
    REP --> STORE[(JSON run store)]
    STORE --> API
    API --> UI
```

## Components
| Component | Responsibility | Never does |
| --- | --- | --- |
| Diff reader | Structured Change object | Judge impact |
| Graph builder | Real dependency edges with file and line | Guess edges |
| Decider 2B | Choose next tool + confidence | Run tools, score risk |
| Tools | Gather Evidence (path, lines, excerpt) | Decide what runs next |
| Risk scoring | Deterministic score from documented factors | Use an LLM |
| Bedrock | Explain evidence in prose | Invent facts or scores |

## Data shapes
`Change`, `Evidence`, `Finding`, `DecisionStep`, `Report` (Pydantic, from Part 1).
A run is stored as one JSON file containing the change, graph, decision trace, findings and report.
