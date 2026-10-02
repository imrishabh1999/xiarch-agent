# Self-evaluation (live mode, 2026-10-02 15:32)

| ID | What it tests | Injected fault | Expected | Outcome | Pass | Findings | Recoveries (ok/total) | Replans | Tool calls | LLM calls | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G1 | happy path | - | complete | complete | yes | 3 | 0/0 | 0 | 4 | 2 | 12.6 |
| G2 | different domain | - | complete | complete | yes | 3 | 2/2 | 0 | 6 | 2 | 11.9 |
| G3 | timeouts -> retry | search:timeout:2 | complete | complete | yes | 3 | 2/2 | 0 | 5 | 2 | 10.1 |
| G4 | empty -> reformulate | search:empty:1 | complete | complete | yes | 3 | 0/3 | 0 | 6 | 3 | 11.7 |
| G5 | malformed output -> retry | search:garbage:1 | complete | complete | yes | 3 | 3/3 | 0 | 7 | 2 | 13.8 |
| G6 | total outage -> replan -> honest failed report | search:error:all | failed | failed | yes | 0 | 0/18 | 1 | 18 | 2 | 23.3 |
| G7 | ambiguous goal | - | clarification | clarification | yes | 0 | 0/0 | 0 | 0 | 0 | 0.6 |
| G8 | almost no real news -> no padding | - | partial/failed | failed | yes | 0 | 0/15 | 1 | 15 | 2 | 36.5 |

## Summary
- Goals meeting the expected outcome: **8/8** (100%)
- Recovery actions that led to a successful step: **7/43**
- Average tool calls per executed run: 8.7 (budget 20)
- Average time per goal: 15.1s

Goal texts:
- G1: Find the top 3 developments in solid-state batteries from the last week
- G2: Find the top 3 developments in AI regulation from the last week
- G3: Find the top 3 developments in quantum computing from the last week
- G4: Find the top 3 developments in solid-state batteries from the last week
- G5: Find the top 3 developments in solid-state batteries from the last week
- G6: Find the top 3 developments in renewable energy from the last week
- G7: do the thing
- G8: Find the top 3 developments in competitive underwater basket weaving from the last week