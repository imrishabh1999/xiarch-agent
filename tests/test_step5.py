import json

from agent.critic import Critic, in_window, requested_count
from agent.executor import Executor, Limits
from agent.llm import MockLLM
from agent.planner import Planner
from agent.recovery import decide
from agent.state import RunState, Step
from agent.tools.base import Tool, ToolResult, ToolRouter
from agent.tools.calculator import Calculator
from agent.tools.fault_injection import apply_injections
from agent.tools.web_search import WebSearch
from agent.tools.write_file import WriteFile

FIX = json.loads(open("data/mock_llm.json", encoding="utf-8").read())
GOAL = "Find the top 3 developments in solid-state batteries from the last week"


def run(tmp_path, inject=(), fixtures=None, cache=None, search=None):
    tools = apply_injections([search or WebSearch(backend="mock"), Calculator(), WriteFile(out_dir=tmp_path)],
                             list(inject))
    router = ToolRouter(tools)
    llm = MockLLM(json.loads(json.dumps(fixtures or FIX)))
    planner = Planner(llm, router)
    state = RunState(goal=GOAL)
    state.interpretation, state.assumptions, state.plan = planner.plan(GOAL)
    Executor(router, llm, planner=planner, cache=cache, limits=Limits(backoff_base=0),
             emit=lambda e: None).run(state)
    return state


def actions(s):
    return [r["action"] for r in s.recoveries]


def test_happy_path_is_complete_and_excludes_stale_result(tmp_path):
    s = run(tmp_path)
    assert s.scratchpad["status"] == "complete" and not s.recoveries
    stale = [r for r in s.scratchpad["results"] if not r["in_window"]]
    assert len(stale) == 1 and "12" not in str(s.scratchpad["findings"])


def test_empty_results_trigger_reformulation(tmp_path):
    s = run(tmp_path, inject=["search:empty:1"])
    assert actions(s) == ["reformulate"] and s.recoveries[0]["outcome"] == "recovered"
    assert s.plan[0].args["query"] == "solid state battery"


def test_garbage_is_caught_even_though_tool_said_ok(tmp_path):
    s = run(tmp_path, inject=["search:garbage:1"])
    assert s.recoveries[0]["problem"].startswith("malformed") and s.plan[0].status == "done"


def test_hallucinated_evidence_id_is_rejected_and_fixed(tmp_path):
    fx = json.loads(json.dumps(FIX))
    bad = json.loads(json.dumps(fx["reason"]))
    bad["findings"][0]["evidence_ids"] = ["R99"]
    fx["reason"] = [bad, fx["reason"]]
    s = run(tmp_path, fixtures=fx)
    assert actions(s) == ["retry_with_feedback"] and "R99" in s.recoveries[0]["problem"]
    assert s.scratchpad["status"] == "complete"


def test_too_few_findings_gathers_more_then_accepts_partial(tmp_path):
    fx = json.loads(json.dumps(FIX))
    one = {"findings": fx["reason"]["findings"][:1], "notes": "only one distinct development"}
    fx["reason"] = [one, one, one]
    s = run(tmp_path, fixtures=fx)
    assert "gather_more" in actions(s)
    assert s.scratchpad["status"] == "partial"           # honest: 1 of 3, never padded


def test_cache_fallback_after_repeated_timeouts(tmp_path):
    today = __import__("datetime").date.today().isoformat()
    cached = [{"title": "cached item", "url": "https://example.com/c", "snippet": "s", "date": today, "source": "x"}]
    s = run(tmp_path, inject=["search:timeout:3"],
            cache=lambda q: ToolResult(ok=True, output=json.dumps(cached), meta={"source": "cache", "cached_at": today}))
    assert s.plan[0].status == "done" and "fallback_cache" in actions(s)
    assert s.scratchpad["results"][0]["origin"] == "cache"


def test_total_failure_replans_once_then_writes_honest_partial_report(tmp_path):
    s = run(tmp_path, inject=["search:error:all"])
    assert s.replans == 1 and len(s.plan) == 8
    assert s.scratchpad["status"].startswith("failed")
    report = (tmp_path / "report.md").read_text()
    assert "failed" in report and "Problems and recovery" in report


def test_stale_search_results_rejected():
    class Old(Tool):
        name, description, schema = "web_search", "", {"query": {"type": "string", "required": True}}
        def run(self, query):
            return ToolResult(ok=True, output=json.dumps([{"url": "u", "date": "2020-01-01"}]))
    step = Step(id=1, description="", tool="web_search", args={}, rationale="")
    ok, why = Critic().check(step, Old().run(query="q"), RunState(goal="g"))
    assert not ok and why.startswith("stale")


def test_policy_table_and_helpers():
    assert decide("web_search", "timeout: x") == "retry"
    assert decide("web_search", "empty: x") == "reformulate"
    assert decide("calculator", "bind_failed: x") == "rebind"
    assert decide("reason", "too_few: x") == "gather_more"
    assert requested_count("give me the top three items") == 3 and requested_count("battery news") is None
    assert not in_window("") and not in_window("2020-01-01")


def test_planner_ignores_content_for_write_file():
    fx = json.loads(json.dumps(FIX))
    fx["plan"]["steps"][4]["args"] = {"path": "r.md", "content": "{{reason_output}}"}
    router = ToolRouter([WebSearch(backend="mock"), Calculator(), WriteFile()])
    _, _, steps = Planner(MockLLM(fx), router).plan(GOAL)
    assert steps[-1].args == {"path": "r.md"}
