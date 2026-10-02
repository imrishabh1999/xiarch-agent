import json

from agent.critic import Critic
from agent.executor import Executor, Limits
from agent.llm import MockLLM
from agent.planner import Planner
from agent.state import RunState
from agent.tools.base import ToolRouter, ToolResult
from agent.tools.calculator import Calculator
from agent.tools.fault_injection import apply_injections
from agent.tools.web_search import WebSearch
from agent.tools.write_file import WriteFile


def run(tmp_path, inject=(), limits=None):
    tools = apply_injections([WebSearch(backend="mock"), Calculator(), WriteFile(out_dir=tmp_path)], list(inject))
    router, llm = ToolRouter(tools), MockLLM()
    state = RunState(goal="top 3 solid-state battery developments")
    state.interpretation, state.assumptions, state.plan = Planner(llm, router).plan(state.goal)
    Executor(router, llm, limits=limits or Limits(backoff_base=0), cache=None, emit=lambda e: None).run(state)
    return state


def test_happy_path_completes_every_step(tmp_path):
    s = run(tmp_path)
    assert [x.status for x in s.plan] == ["done"] * 5
    assert len(s.scratchpad["results"]) == 5                 # two searches, duplicates removed by URL
    assert float(s.scratchpad["calculations"][0]["value"]) == 80  # bound at runtime: 4/5*100
    assert len(s.scratchpad["findings"]) == 3 and (tmp_path / "report.md").exists()


def test_injected_timeout_is_retried_and_recovers(tmp_path):
    s = run(tmp_path, inject=["search:timeout:1"])
    assert s.plan[0].status == "done" and s.plan[0].attempts == 2
    assert any(e["event"] == "recovery" and e["action"] == "retry" for e in s.history)


def test_step_fails_after_max_attempts_but_run_continues(tmp_path):
    s = run(tmp_path, inject=["search:timeout:3"])            # step 1 times out 3 times
    assert s.plan[0].status == "failed" and s.plan[0].attempts == 3
    assert s.plan[1].status == "done" and s.plan[-1].status == "done"


def test_dependent_step_skipped_when_all_inputs_failed(tmp_path):
    s = run(tmp_path, inject=["search:error:all"])
    assert [x.status for x in s.plan[:2]] == ["failed", "failed"]
    assert s.plan[2].status == "skipped" and s.plan[3].status == "skipped"


def test_tool_budget_stops_the_loop(tmp_path):
    s = run(tmp_path, inject=["search:timeout:all"], limits=Limits(max_tool_calls=4, backoff_base=0))
    assert s.tool_calls == 4 and "budget" in s.stop_reason
    assert s.plan[-1].status == "skipped"


def test_critic_rejects_garbage():
    from agent.state import Step
    step = Step(id=1, description="", tool="web_search", args={}, rationale="")
    ok, why = Critic().check(step, ToolResult(ok=True, output="<html>not json"), RunState(goal="g"))
    assert not ok and why.startswith("malformed")
