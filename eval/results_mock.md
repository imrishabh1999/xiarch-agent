# Self-evaluation (mock mode, 2026-10-02 14:15)

| ID | What it tests | Injected fault | Expected | Outcome | Pass | Findings | Recoveries (ok/total) | Replans | Tool calls | LLM calls | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 | happy path | - | complete | complete | yes | 3 | 0/0 | 0 | 4 | 3 | 0.0 |
| G4 | empty -> reformulate | search:empty:1 | complete | complete | yes | 3 | 1/1 | 0 | 5 | 4 | 0.0 |
| G5 | malformed output -> retry | search:garbage:1 | complete | complete | yes | 3 | 1/1 | 0 | 5 | 3 | 0.0 |
| G6 | total outage -> replan -> honest failed report | search:error:all | failed | failed | yes | 0 | 0/6 | 1 | 9 | 2 | 0.0 |

## Summary
- Goals meeting the expected outcome: **4/4** (100%)
- Recovery actions that led to a successful step: **2/8**
- Average tool calls per executed run: 5.8 (budget 20)
- Average time per goal: 0.0s

Goal texts:
- G1: Find the top 3 developments in solid-state batteries from the last week
- G4: Find the top 3 developments in solid-state batteries from the last week
- G5: Find the top 3 developments in solid-state batteries from the last week
- G6: Find the top 3 developments in renewable energy from the last week