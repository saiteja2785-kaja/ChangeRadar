# Decision pattern: "typed question, allowed options, validated choice, safe fallback"

## Why
A small decision model is good at picking one option from a list. It is not good at running tools or writing prose.
So we give it exactly one job: pick the next investigation tool.

## The pattern
1. **Typed question**: "Which investigation tool should run next?"
2. **Allowed options with one-line descriptions**: the five tools.
3. **Compact state**: changed symbol, evidence found so far, unanswered questions, remaining steps.
4. **Call Decider 2B** and receive `(choice, confidence)`.
5. **Validate**: the choice must be in the allowed set.
6. **Confidence gate**: if confidence < threshold, or the output is invalid, use a fixed-priority fallback.
7. **Log every decision**: state, options, choice, confidence, fallback used (yes/no).

## Why this is safe
- The model can only choose from a closed list, and invalid output never executes.
- Low confidence degrades to a deterministic order, so the loop always makes progress.
- A step budget guarantees termination.
- Every decision is in the trace, so a reviewer can audit it.

## Example trace row
| Step | Options | Choice | Confidence | Fallback |
| --- | --- | --- | --- | --- |
| 1 | 5 tools | trace_consumers | TODO (from real run) | no |

Fill the table from a real run. Do not invent values.

## Reusing it
Replace the question, options and state builder, keep validation, gate and logging.
See `TODO: examples/decider_reuse_example.py`.
