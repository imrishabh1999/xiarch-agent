from eval.run_eval import score, to_markdown
from agent.main import run_goal


def test_mock_eval_rows_and_table():
    goals = [{"id": "G1", "goal": "Find the top 3 developments in solid-state batteries from the last week",
              "inject": [], "expect": ["complete"], "tests": "happy"},
             {"id": "G6", "goal": "x", "inject": ["search:error:all"], "expect": ["failed"], "tests": "outage"}]
    rows = [score(g, run_goal(g["goal"], mock=True, inject=g["inject"], show=lambda e: None, say=lambda m: None))
            for g in goals]
    assert [r["passed"] for r in rows] == [True, True] and rows[1]["replans"] == 1
    md = to_markdown(rows, "mock")
    assert "**2/2**" in md and "| G6 |" in md
