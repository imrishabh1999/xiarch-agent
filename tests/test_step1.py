from agent.state import RunState, Step
from agent.tools.base import ToolRouter
from agent.tools.calculator import Calculator

router = ToolRouter([Calculator()])


def test_calculator_does_arithmetic():
    r = router.call("calculator", {"expression": "2 + 2 * 3"})
    assert r.ok and r.output == "8"


def test_calculator_rejects_code():
    r = router.call("calculator", {"expression": "__import__('os').system('dir')"})
    assert not r.ok and "rejected" in r.error


def test_division_by_zero_is_an_error_not_a_crash():
    r = router.call("calculator", {"expression": "1/0"})
    assert not r.ok and r.error == "division by zero"


def test_router_rejects_unknown_tool():
    r = router.call("rocket_launcher", {})
    assert not r.ok and r.error.startswith("invalid_args: unknown tool")


def test_router_rejects_bad_arguments():
    r = router.call("calculator", {"expression": 42})
    assert not r.ok and "must be string" in r.error
    r = router.call("calculator", {})
    assert not r.ok and "missing required" in r.error


def test_state_starts_empty():
    s = RunState(goal="test", plan=[Step(1, "add", "calculator", {"expression": "1+1"}, "check")])
    assert s.plan[0].status == "pending" and s.tool_calls == 0
