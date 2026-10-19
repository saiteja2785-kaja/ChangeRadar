"""Part 6 probe: send one real question to the local Decider 2B server and print the raw reply."""
import json

import httpx

from backend.app.tools import tool_descriptions

URL = "http://127.0.0.1:8000/v1/systemone"

state = (
    "Change under investigation: the API field 'price' changed from rupees to paise "
    "(500 became 50000). Evidence found so far: none. "
    "Unanswered questions: which components read price, and do they convert paise to rupees? "
    "Remaining investigation steps: 5."
)

payload = {
    "state": state,
    "questions": {
        "next_tool": {
            "type": "choice",
            "instructions": "Which investigation tool should run next?",
            "criteria": tool_descriptions(),
        },
        "enough_evidence": {
            "type": "noul",
            "instructions": "Has enough evidence been gathered to write the final report?",
        },
    },
}

response = httpx.post(URL, json=payload, timeout=300)
print("HTTP", response.status_code)
print(json.dumps(response.json(), indent=2))
