"""CLI: python -m agent.main "goal" [--mock] [--inject search:timeout:1 ...]"""
import argparse
import json
import time

from agent.executor import Executor, Limits
from agent.llm import GroqLLM, MockLLM
from agent.planner import ClarificationNeeded, Planner, PlanError, format_plan
from agent.report import build, render
from agent.state import RunState
from agent.tools.base import ToolRouter
from agent.tools.calculator import Calculator
from agent.tools.fault_injection import apply_injections
from agent.tools.web_search import WebSearch, cache_lookup
from agent.tools.write_file import WriteFile
from agent.trace import TraceLogger


def show(event: dict):
    e = event["event"]
    if e == "step_start":
        print(f"\n>> step {event['step']} [{event['tool']}] {event['description']}")
    elif e == "tool_call":
        status = "ok" if event["ok"] else f"FAILED: {event['error']}"
        print(f"   call {event['tool']}({json.dumps(event['args'])[:100]}) -> {status}")
    elif e == "verdict":
        print(f"   critic: {'PASS' if event['passed'] else 'REJECT'} ({event['reason']})")
    elif e in ("replan", "new_plan", "replan_failed", "fallback_report"):
        print(f"\n!! {e}: " + ", ".join(f"{k}={v}" for k, v in event.items() if k not in ("t", "event")))
    elif e == "skip":
        print(f"\n>> step {event['step']} SKIPPED: {event['reason']}")
    elif e in ("step_failed", "guard_stop", "bind", "reason", "recovery", "reformulated",
               "evidence", "cache_fallback", "reformulate_failed"):
        print(f"   {e}: " + ", ".join(f"{k}={v}" for k, v in event.items() if k not in ("t", "event", "step")))


def run_goal(goal: str, mock: bool = False, inject: list[str] | None = None, show=show, say=print) -> dict:
    """Plan + execute one goal. Returns a summary dict; also used by eval/run_eval.py."""
    t0 = time.monotonic()
    tools = apply_injections([WebSearch(backend="mock" if mock else "live"), Calculator(), WriteFile()],
                             inject or [])
    router, llm = ToolRouter(tools), (MockLLM() if mock else GroqLLM())
    planner = Planner(llm, router)
    state = RunState(goal=goal)
    out = {"goal": goal, "inject": inject or [], "state": state, "run_dir": None}
    try:
        state.interpretation, state.assumptions, state.plan = planner.plan(goal)
        state.llm_calls += llm.calls
    except ClarificationNeeded as q:
        say(f"Goal is too vague. Question for you: {q}")
        return {**out, "outcome": "clarification", "question": str(q), "seconds": round(time.monotonic() - t0, 1)}
    except PlanError as e:
        say(f"Could not build a valid plan: {e}")
        return {**out, "outcome": "error", "error": str(e), "seconds": round(time.monotonic() - t0, 1)}

    say(format_plan(state.interpretation, state.assumptions, state.plan))
    log = TraceLogger(show)
    log.save("plan.txt", format_plan(state.interpretation, state.assumptions, state.plan))
    try:
        Executor(router, llm, planner=planner, limits=Limits(backoff_base=0 if mock else 1.0),
                 cache=None if mock else cache_lookup, emit=log).run(state)
    finally:
        data = build(state)
        log.save("report.json", json.dumps(data, indent=2))
        log.save("report.md", render(data))
        log.close()
    status = state.scratchpad.get("status", "")
    outcome = "complete" if status == "complete" else "partial" if status == "partial" else "failed"
    return {**out, "outcome": outcome, "status": status, "run_dir": log.dir.name, "llm_calls": llm.calls,
            "seconds": round(time.monotonic() - t0, 1)}


def main():
    ap = argparse.ArgumentParser(description="Planning research agent")
    ap.add_argument("goal")
    ap.add_argument("--mock", action="store_true", help="no API key / internet: mock LLM + mock search")
    ap.add_argument("--inject", action="append", default=[], help="fault injection, e.g. search:timeout:1")
    a = ap.parse_args()
    r = run_goal(a.goal, a.mock, a.inject)
    if not r["run_dir"]:
        return
    state = r["state"]
    print("\n" + "=" * 60)
    for s in state.plan:
        print(f"step {s.id} {s.tool:<11} {s.status:<8} attempts={s.attempts}")
    print(f"status: {r['status']}")
    print(f"report: outputs/report.md   full record: runs/{r['run_dir']}/ (trace.jsonl, report.json, report.md)")
    print(f"tool calls={state.tool_calls}  llm calls={r['llm_calls']}  recoveries={len(state.recoveries)}  "
          f"replans={state.replans}  time={r['seconds']}s"
          + (f"  stopped early: {state.stop_reason}" if state.stop_reason else ""))


if __name__ == "__main__":
    main()
