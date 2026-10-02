"""Planner: turns a natural-language goal into a validated, ordered plan of tool steps.
The LLM proposes; deterministic code validates. Invalid plans get exactly one corrective re-prompt."""
import json
from datetime import date

from agent.llm import LLM, parse_json
from agent.state import Step
from agent.tools.base import ToolRouter

REASON = "reason"   # pseudo-tool: an LLM thinking step over results gathered so far (no external call)
MIN_STEPS, MAX_STEPS = 3, 7

SYSTEM = """You are the planning module of a research agent. Today is {today}.
Turn the user's goal into a short plan that uses the tools below. Reply with ONE JSON object only.

TOOLS:
{tools}
- "reason": think over results gathered so far (rank, compare, pick, summarise). args: {{}}

RULES:
1. {min_steps}-{max_steps} steps, in execution order, ids starting at 1.
2. Every step: id, description, tool, args, rationale (why this step is needed), depends_on (earlier ids).
3. Search with 2-3 differently-worded queries so one bad query does not sink the run.
   Keep queries short and natural (3-6 words). Never put dates or date ranges in a query:
   web_search already returns only the last 7 days.
4. If a step's arguments depend on earlier results (e.g. a calculation on numbers you have not found yet),
   set "bind_at_runtime": true and "args": {{}}. Otherwise give concrete args.
5. Use only facts the tools return. Never plan to "recall" facts from memory.
6. Interpret vague goals sensibly and write every interpretation choice in "assumptions".
   Only if the goal cannot be interpreted at all, return {{"clarification_needed": "<one question>"}}.
7. The last step saves the report with write_file. Give only {{"path": "report.md"}}:
   the agent writes the content itself from verified findings.

JSON FORMAT:
{{"interpretation": "...", "assumptions": ["..."], "steps": [{{"id": 1, "description": "...", "tool": "web_search",
"args": {{"query": "..."}}, "rationale": "...", "depends_on": [], "bind_at_runtime": false}}]}}"""


class PlanError(Exception):
    pass


class ClarificationNeeded(Exception):
    pass


class Planner:
    def __init__(self, llm: LLM, router: ToolRouter):
        self.llm, self.router = llm, router

    def _system(self) -> str:
        return SYSTEM.format(today=date.today().isoformat(), tools=json.dumps(self.router.describe(), indent=1),
                             min_steps=MIN_STEPS, max_steps=MAX_STEPS)

    def plan(self, goal: str) -> tuple[str, list[str], list[Step]]:
        user = f"GOAL: {goal}"
        raw = self.llm.complete(self._system(), user, stage="plan")
        result, problems = self._check(raw)
        if problems:  # one corrective re-prompt, with the exact problems listed
            fix = (f"{user}\n\nYour previous reply was rejected:\n- " + "\n- ".join(problems) +
                   f"\n\nPrevious reply:\n{raw[:3000]}\n\nReturn a corrected JSON plan.")
            raw = self.llm.complete(self._system(), fix, stage="plan")
            result, problems = self._check(raw)
            if problems:
                raise PlanError("plan still invalid after one re-prompt: " + "; ".join(problems))
        return result

    def replan(self, goal: str, done: list[Step], failure: str) -> tuple[str, list[str], list[Step]]:
        """Called once by recovery when the current plan cannot continue. Completed steps are kept."""
        summary = "\n".join(f"- step {s.id} ({s.tool}) {s.status}: {s.description}" for s in done)
        user = (f"GOAL: {goal}\n\nSteps already completed:\n{summary or '- none'}\n\n"
                f"The plan cannot continue because: {failure}\n"
                f"Make a NEW plan for the remaining work only, avoiding the approach that failed. "
                f"Number steps from {len(done) + 1}.")
        raw = self.llm.complete(self._system(), user, stage="replan")
        result, problems = self._check(raw, first_id=len(done) + 1, min_steps=1)
        if problems:
            raise PlanError("replan invalid: " + "; ".join(problems))
        return result

    def _check(self, raw: str, first_id: int = 1, min_steps: int = MIN_STEPS):
        """Deterministic validation. Returns (result, []) or (None, problems)."""
        try:
            data = parse_json(raw)
        except ValueError as e:
            return None, [f"not valid JSON: {e}"]
        if data.get("clarification_needed"):
            raise ClarificationNeeded(str(data["clarification_needed"]))
        steps_raw, problems = data.get("steps"), []
        if not isinstance(steps_raw, list):
            return None, ["'steps' must be a list"]
        if not min_steps <= len(steps_raw) <= MAX_STEPS:
            problems.append(f"plan has {len(steps_raw)} steps; need {min_steps}-{MAX_STEPS}")
        steps, seen = [], set()
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                problems.append(f"step #{i + 1} is not an object")
                continue
            sid, tool, args = s.get("id"), s.get("tool"), s.get("args") or {}
            late = bool(s.get("bind_at_runtime"))
            if sid != first_id + i:
                problems.append(f"step ids must run {first_id},{first_id + 1},... (got {sid} at position {i + 1})")
            for key in ("description", "rationale"):
                if not str(s.get(key, "")).strip():
                    problems.append(f"step {sid}: missing {key}")
            if tool == "write_file":   # content is produced by the agent, never by the planner
                args = {"path": str(args.get("path") or "report.md")}
                err = None
            elif tool != REASON:
                err = None if late and not args else self.router.validate(tool, args)
            else:
                err = None
            if err:
                problems.append(f"step {sid}: {err}")
            deps = s.get("depends_on") or []
            bad = [d for d in deps if d not in seen and d >= first_id]
            if bad:
                problems.append(f"step {sid}: depends_on {bad} must refer to earlier steps")
            seen.add(sid)
            steps.append(Step(id=sid, description=s.get("description", ""), tool=tool, args=args,
                              rationale=s.get("rationale", ""), depends_on=deps, bind_at_runtime=late))
        if steps and steps[-1].tool != "write_file":
            problems.append("last step must save the report with write_file")
        if problems:
            return None, problems
        return (str(data.get("interpretation", "")), [str(a) for a in data.get("assumptions", [])], steps), []


def format_plan(interpretation: str, assumptions: list[str], steps: list[Step]) -> str:
    """The visible planning trace printed before execution."""
    lines = ["=" * 60, "PLAN", "=" * 60, f"Understood goal as: {interpretation}"]
    if assumptions:
        lines.append("Assumptions:")
        lines += [f"  - {a}" for a in assumptions]
    for s in steps:
        dep = f"  (after {', '.join(map(str, s.depends_on))})" if s.depends_on else ""
        args = "<filled at runtime from earlier results>" if s.bind_at_runtime else json.dumps(s.args)[:90]
        lines += [f"[{s.id}] {s.tool}: {s.description}{dep}", f"     args: {args}", f"     why : {s.rationale}"]
    return "\n".join(lines)


if __name__ == "__main__":   # quick manual check: python -m agent.planner "goal" [--mock]
    import sys
    from agent.llm import GroqLLM, MockLLM
    from agent.tools.calculator import Calculator
    from agent.tools.web_search import WebSearch
    from agent.tools.write_file import WriteFile
    mock = "--mock" in sys.argv
    goal = next((a for a in sys.argv[1:] if not a.startswith("--")),
                "Find the top 3 developments in solid-state batteries from the last week")
    router = ToolRouter([WebSearch(backend="mock" if mock else "live"), Calculator(), WriteFile()])
    llm = MockLLM() if mock else GroqLLM()
    try:
        print(format_plan(*Planner(llm, router).plan(goal)))
    except ClarificationNeeded as q:
        print(f"Goal is too vague. Question for the user: {q}")
    print(f"\nLLM calls: {llm.calls}")
