import copy
import json

import pytest

from agent.llm import MockLLM, parse_json
from agent.planner import ClarificationNeeded, Planner, PlanError, format_plan
from agent.tools.base import ToolRouter
from agent.tools.calculator import Calculator
from agent.tools.web_search import WebSearch
from agent.tools.write_file import WriteFile

ROUTER = ToolRouter([WebSearch(backend="mock"), Calculator(), WriteFile()])
GOOD = json.loads(open("data/mock_llm.json", encoding="utf-8").read())["plan"]


def planner(*replies):
    return Planner(MockLLM({"plan": list(replies)}), ROUTER)


def test_valid_plan_parsed_and_printed():
    interp, assumptions, steps = planner(GOOD).plan("top 3 solid-state battery developments")
    assert len(steps) == 5 and steps[2].bind_at_runtime and assumptions
    text = format_plan(interp, assumptions, steps)
    assert "Assumptions:" in text and "why :" in text and "filled at runtime" in text


def test_parse_json_strips_fences_and_chatter():
    assert parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}


def test_invalid_plan_gets_one_reprompt_then_succeeds():
    bad = copy.deepcopy(GOOD)
    bad["steps"][0]["tool"] = "google_search"          # tool that does not exist
    p = planner(bad, GOOD)
    p.plan("goal")
    assert p.llm.calls == 2
    assert "unknown tool 'google_search'" in p.llm.seen[1][1]   # the re-prompt names the exact problem


def test_invalid_twice_raises():
    with pytest.raises(PlanError):
        planner("not json at all", "still not json").plan("goal")


def test_bad_dependencies_and_length_rejected():
    bad = copy.deepcopy(GOOD)
    bad["steps"][0]["depends_on"] = [4]                  # depends on a later step
    bad["steps"] = bad["steps"][:1] + bad["steps"][3:]   # also renumbering breaks
    with pytest.raises(PlanError):
        planner(bad, bad).plan("goal")


def test_vague_goal_asks_for_clarification():
    with pytest.raises(ClarificationNeeded):
        planner({"clarification_needed": "Which topic should I research?"}).plan("do the thing")
