"""Self-evaluation: run every goal in eval/goals.json and score the agent.
python -m eval.run_eval            (live: Groq + real search)
python -m eval.run_eval --mock     (offline subset; deterministic)"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from agent.main import run_goal

HERE = Path(__file__).resolve().parent


def score(goal: dict, r: dict) -> dict:
    s = r["state"]
    rec = s.recoveries
    return {"id": goal["id"], "tests": goal["tests"], "goal": goal["goal"], "inject": ",".join(goal["inject"]) or "-",
            "expected": "/".join(goal["expect"]), "outcome": r["outcome"], "passed": r["outcome"] in goal["expect"],
            "findings": len(s.scratchpad.get("findings", [])), "recoveries": len(rec),
            "recovered": sum(x.get("outcome") == "recovered" for x in rec), "replans": s.replans,
            "tool_calls": s.tool_calls, "llm_calls": r.get("llm_calls", s.llm_calls), "seconds": r["seconds"],
            "run_dir": r["run_dir"]}


def to_markdown(rows: list[dict], mode: str) -> str:
    n, passed = len(rows), sum(r["passed"] for r in rows)
    rec, ok = sum(r["recoveries"] for r in rows), sum(r["recovered"] for r in rows)
    ran = [r for r in rows if r["run_dir"]]
    L = [f"# Self-evaluation ({mode} mode, {datetime.now():%Y-%m-%d %H:%M})", "",
         "| ID | What it tests | Injected fault | Expected | Outcome | Pass | Findings | Recoveries (ok/total) "
         "| Replans | Tool calls | LLM calls | Time (s) |", "|---" * 12 + "|"]
    for r in rows:
        L.append(f"| {r['id']} | {r['tests']} | {r['inject']} | {r['expected']} | {r['outcome']} | "
                 f"{'yes' if r['passed'] else '**no**'} | {r['findings']} | {r['recovered']}/{r['recoveries']} | "
                 f"{r['replans']} | {r['tool_calls']} | {r['llm_calls']} | {r['seconds']} |")
    L += ["", "## Summary",
          f"- Goals meeting the expected outcome: **{passed}/{n}** ({passed / n:.0%})",
          f"- Recovery actions that led to a successful step: **{ok}/{rec}**" + (" (none needed)" if not rec else ""),
          f"- Average tool calls per executed run: {sum(r['tool_calls'] for r in ran) / max(len(ran), 1):.1f} "
          f"(budget 20)",
          f"- Average time per goal: {sum(r['seconds'] for r in rows) / n:.1f}s",
          "", "Goal texts:"] + [f"- {r['id']}: {r['goal']}" for r in rows]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--only", help="comma-separated goal ids, e.g. G1,G7")
    a = ap.parse_args()
    goals = json.loads((HERE / "goals.json").read_text(encoding="utf-8"))["goals"]
    if a.mock:
        goals = [g for g in goals if g["mock"]]
    if a.only:
        goals = [g for g in goals if g["id"] in a.only.split(",")]
    rows = []
    for g in goals:
        print(f"[{g['id']}] {g['tests']}: {g['goal']}  inject={g['inject'] or '-'}", flush=True)
        r = run_goal(g["goal"], mock=a.mock, inject=g["inject"], show=lambda e: None, say=lambda m: None)
        rows.append(score(g, r))
        print(f"      -> {r['outcome']}  ({'PASS' if rows[-1]['passed'] else 'FAIL'}, {r['seconds']}s)", flush=True)
        if not a.mock:
            time.sleep(3)          # stay polite to the free search and LLM tiers
    mode = "mock" if a.mock else "live"
    md = to_markdown(rows, mode)
    (HERE / f"results_{mode}.md").write_text(md, encoding="utf-8")
    (HERE / f"results_{mode}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
