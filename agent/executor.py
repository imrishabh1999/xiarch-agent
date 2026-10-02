"""Executor: runs the plan step by step with hard guardrails and a recovery policy.
Per step: bind args if needed -> call tool -> critic verdict -> recovery action -> try again.
Escalation: search out of attempts -> cache fallback; no usable evidence -> one replan;
the run ALWAYS ends with a saved report, even a partial one. Nothing fails silently."""
import json
import time
from datetime import date
from typing import Callable

from agent.critic import Critic, in_window
from agent.llm import LLM, LLMError, parse_json
from agent.planner import REASON, Planner, PlanError
from agent.recovery import decide
from agent.report import compute_status, markdown_report
from agent.state import RunState, Step
from agent.tools.base import ToolResult, ToolRouter
from agent.tools.web_search import cache_lookup


class Limits:
    def __init__(self, max_tool_calls=20, max_attempts=3, max_seconds=240, backoff_base=1.0, max_replans=1):
        self.max_tool_calls, self.max_attempts, self.max_seconds = max_tool_calls, max_attempts, max_seconds
        self.backoff_base, self.max_replans = backoff_base, max_replans


class Executor:
    def __init__(self, router: ToolRouter, llm: LLM, critic: Critic | None = None, limits: Limits | None = None,
                 planner: Planner | None = None, cache: Callable[[str], ToolResult] | None = cache_lookup,
                 report_builder: Callable[[RunState], str] = markdown_report, emit: Callable[[dict], None] = print):
        self.router, self.llm, self.critic, self.planner = router, llm, critic or Critic(), planner
        self.limits, self.cache, self.report_builder, self._emit = limits or Limits(), cache, report_builder, emit

    # ---------- trace ----------
    def emit(self, state: RunState, **event):
        event = {"t": round(time.monotonic() - self.t0, 2), **event}
        state.history.append(event)
        self._emit(event)

    def record(self, state: RunState, step: Step, problem: str, action: str):
        state.recoveries.append({"step": step.id, "attempt": step.attempts, "problem": problem, "action": action})
        self.emit(state, event="recovery", step=step.id, problem=problem, action=action)

    def close_recoveries(self, state: RunState, step: Step):
        verdicts = [e for e in state.history if e.get("event") == "verdict" and e.get("step") == step.id]
        partial = bool(verdicts) and str(verdicts[-1].get("reason", "")).startswith("partial")
        for r in state.recoveries:
            if r["step"] == step.id and "outcome" not in r:
                r["outcome"] = ("partially recovered" if partial else "recovered") if step.status == "done" \
                    else "did not recover"

    # ---------- main loop ----------
    def run(self, state: RunState) -> RunState:
        self.t0 = time.monotonic()
        state.scratchpad.setdefault("results", [])
        self.run_steps(state, state.plan)
        if not self.usable_evidence(state) and not state.stop_reason:
            self.try_replan(state)
        self.finish(state)
        return state

    def run_steps(self, state: RunState, steps: list[Step]):
        for step in steps:
            if state.stop_reason:
                step.status = "skipped"
                continue
            deps = [s for s in state.plan if s.id in step.depends_on]
            if deps and not any(d.status == "done" for d in deps):
                step.status = "skipped"
                self.emit(state, event="skip", step=step.id, reason="every step it depends on failed")
                continue
            if step.tool == "write_file" and not self.usable_evidence(state):
                step.status = "skipped"   # finish() writes an honest partial report instead
                self.emit(state, event="skip", step=step.id, reason="no usable evidence yet")
                continue
            self.run_step(state, step)
            self.close_recoveries(state, step)

    def usable_evidence(self, state: RunState) -> bool:
        return any(r["in_window"] for r in state.scratchpad["results"])

    def try_replan(self, state: RunState):
        if not self.planner or state.replans >= self.limits.max_replans:
            return
        failures = "; ".join(f"step {s.id}: {s.observation}" for s in state.plan if s.status == "failed")
        state.replans += 1
        self.emit(state, event="replan", reason=f"no usable evidence. {failures}")
        try:
            state.llm_calls += 1
            _, extra, steps = self.planner.replan(state.goal, state.plan, failures or "no usable evidence")
        except (PlanError, LLMError) as e:
            self.emit(state, event="replan_failed", reason=str(e))
            return
        state.assumptions += [a for a in extra if a not in state.assumptions]
        state.plan += steps
        self.emit(state, event="new_plan", steps=[f"{s.id}:{s.tool}" for s in steps])
        self.run_steps(state, steps)

    def finish(self, state: RunState):
        """Graceful end: decide the run status and make sure a report exists."""
        state.scratchpad["status"] = compute_status(state)
        if any(s.tool == "write_file" and s.status == "done" for s in state.plan):
            return
        result = self.router.call("write_file", {"path": "report.md", "content": self.report_builder(state)})
        self.emit(state, event="fallback_report", ok=result.ok, error=result.error,
                  note="report written by the agent because the planned write step did not run")

    # ---------- one step ----------
    def guard(self, state: RunState) -> str | None:
        if state.tool_calls >= self.limits.max_tool_calls:
            return f"tool-call budget reached ({self.limits.max_tool_calls})"
        if time.monotonic() - self.t0 > self.limits.max_seconds:
            return f"time limit reached ({self.limits.max_seconds}s)"
        return None

    def run_step(self, state: RunState, step: Step):
        self.emit(state, event="step_start", step=step.id, tool=step.tool, description=step.description)
        while step.attempts < self.limits.max_attempts:
            stop = self.guard(state)
            if stop:
                state.stop_reason, step.status = stop, "failed"
                self.emit(state, event="guard_stop", step=step.id, reason=stop)
                return
            step.attempts += 1
            final = step.attempts == self.limits.max_attempts
            result = self.act(state, step)
            passed, reason = self.critic.check(step, result, state, final_attempt=final)
            self.emit(state, event="verdict", step=step.id, attempt=step.attempts, passed=passed, reason=reason)
            if passed:
                self.absorb(state, step, result)
                step.status = "done"
                return
            step.observation = reason
            if not final:
                self.recover(state, step, reason)
        if step.tool == "web_search" and self.cache_fallback(state, step):
            return
        step.status = "failed"
        self.emit(state, event="step_failed", step=step.id, reason=step.observation)

    def recover(self, state: RunState, step: Step, reason: str):
        action = decide(step.tool, reason)
        self.record(state, step, reason, action)
        if action == "retry":
            wait = self.limits.backoff_base * 2 ** (step.attempts - 1)
            time.sleep(wait)
        elif action == "reformulate":
            self.reformulate(state, step, reason)
        elif action == "rebind":
            step.bind_at_runtime, step.feedback = True, reason
        elif action == "retry_with_feedback":
            step.feedback = reason
        elif action == "gather_more":
            step.feedback = reason
            self.gather_more(state, step)

    # ---------- recovery actions ----------
    def used_queries(self, state: RunState) -> list[str]:
        return [e["args"].get("query", "") for e in state.history
                if e.get("event") == "tool_call" and e.get("tool") == "web_search"]

    def new_query(self, state: RunState, why: str) -> str | None:
        system = ("You rewrite web search queries for a news search limited to the last 7 days. "
                  'Reply with JSON {"query": "..."}: 3-6 words, no dates, different from every query already tried.')
        user = f"Goal: {state.goal}\nProblem: {why}\nQueries already tried: {json.dumps(self.used_queries(state))}"
        try:
            q = str(self.llm_json(state, system, user, stage="reformulate").get("query", "")).strip()
        except (LLMError, ValueError) as e:
            self.emit(state, event="reformulate_failed", reason=str(e))
            return None
        return q if q and q.lower() not in [u.lower() for u in self.used_queries(state)] else None

    def reformulate(self, state: RunState, step: Step, reason: str):
        q = self.new_query(state, reason)
        if q:
            step.args = {**step.args, "query": q}
            self.emit(state, event="reformulated", step=step.id, query=q)

    def gather_more(self, state: RunState, step: Step):
        """Reasoning found too few developments: one extra, broader search before reasoning again."""
        if self.guard(state):
            return
        q = self.new_query(state, f"{step.feedback}. Need a broader query to find more distinct developments")
        if not q:
            return
        extra = Step(id=step.id, description="extra search requested by recovery", tool="web_search",
                     args={"query": q, "max_results": 10}, rationale="too few findings")
        state.tool_calls += 1
        result = self.router.call("web_search", extra.args)
        ok, why = self.critic.check(extra, result, state)
        self.emit(state, event="tool_call", step=step.id, tool="web_search", args=extra.args, ok=result.ok,
                  error=result.error, meta=result.meta, note="recovery: gather_more")
        if ok:
            before = len(state.scratchpad["results"])
            self.absorb(state, extra, result)
            step.feedback += f". {len(state.scratchpad['results']) - before} new results were added; use them."

    def cache_fallback(self, state: RunState, step: Step) -> bool:
        if not self.cache:
            return False
        result = self.cache(step.args.get("query", ""))
        ok, why = self.critic.check(step, result, state) if result.ok else (False, result.error)
        self.record(state, step, step.observation or "", "fallback_cache")
        self.emit(state, event="cache_fallback", step=step.id, ok=ok, reason=why,
                  cached_at=result.meta.get("cached_at"))
        if ok:
            self.absorb(state, step, result)
            step.status = "done"
        return ok

    # ---------- one attempt ----------
    def act(self, state: RunState, step: Step) -> ToolResult:
        if step.tool == REASON:
            return self.reason(state, step)
        if step.tool == "write_file":
            step.args = {"path": step.args.get("path") or "report.md", "content": self.report_builder(state)}
        elif step.bind_at_runtime:
            err = self.bind(state, step)
            if err:
                return ToolResult(ok=False, output="", error=f"bind_failed: {err}")
        state.tool_calls += 1
        result = self.router.call(step.tool, step.args)
        shown = {k: (v[:60] + "...") if isinstance(v, str) and len(v) > 60 else v for k, v in step.args.items()}
        self.emit(state, event="tool_call", step=step.id, tool=step.tool, args=shown, ok=result.ok,
                  error=result.error, meta=result.meta)
        return result

    def llm_json(self, state: RunState, system: str, user: str, stage: str) -> dict:
        state.llm_calls += 1
        return parse_json(self.llm.complete(system, user, stage=stage))

    def evidence_text(self, state: RunState, only_fresh: bool = True) -> str:
        rows = [r for r in state.scratchpad["results"] if r["in_window"] or not only_fresh]
        return "\n".join(f"[{r['id']}] {r['date'] or 'no date'} | {r['source']} | {r['title']} | {r['snippet'][:200]}"
                         for r in rows) or "(no results gathered)"

    def bind(self, state: RunState, step: Step) -> str | None:
        """Fill arguments that depended on earlier results, using only gathered evidence."""
        system = ("You fill in tool arguments using ONLY the evidence given. Reply with one JSON object "
                  "containing exactly the tool's arguments.")
        res = state.scratchpad["results"]
        user = (f"Today: {date.today().isoformat()}\nTask: {step.description}\nTool: {step.tool}\n"
                f"Argument schema: {json.dumps(self.router.tools[step.tool].schema)}\n"
                f"Facts: {len(res)} results gathered, {sum(r['in_window'] for r in res)} dated within 7 days.\n"
                + (f"Your previous arguments were rejected: {step.feedback}\n" if step.feedback else "")
                + f"\nEvidence:\n{self.evidence_text(state, only_fresh=False)}")
        try:
            args = self.llm_json(state, system, user, stage="bind")
        except (LLMError, ValueError) as e:
            return str(e)
        problem = self.router.validate(step.tool, args)
        if problem:
            return problem
        step.args = args
        self.emit(state, event="bind", step=step.id, args=args)
        return None

    def reason(self, state: RunState, step: Step) -> ToolResult:
        system = ("You analyse search results for a research agent. Use ONLY the evidence listed. "
                  "Every finding must cite evidence ids like R1. Cite EVERY listed result that reports the same "
                  "development (corroboration matters), but each id may support only one finding. "
                  "Do not add facts that are not in the evidence. If the evidence supports fewer distinct "
                  "developments than requested, return fewer and say why in notes; never pad. "
                  'Reply with JSON: {"findings": [{"title": "...", "summary": "...", "evidence_ids": ["R1"], '
                  '"why_selected": "..."}], "notes": "..."}')
        user = (f"Goal: {state.goal}\nToday: {date.today().isoformat()}\nTask: {step.description}\n"
                + (f"Your previous answer was rejected: {step.feedback}\n" if step.feedback else "")
                + f"\nEvidence (all dated within the last 7 days):\n{self.evidence_text(state)}")
        try:
            data = self.llm_json(state, system, user, stage="reason")
        except (LLMError, ValueError) as e:
            return ToolResult(ok=False, output="", error=f"reason_failed: {e}")
        self.emit(state, event="reason", step=step.id, findings=len(data.get("findings", [])))
        return ToolResult(ok=True, output=json.dumps(data))

    # ---------- store what a successful step produced ----------
    def absorb(self, state: RunState, step: Step, result: ToolResult):
        step.observation = result.output[:300]
        pad = state.scratchpad
        if step.tool == "web_search":
            known, added, fresh = {r["url"] for r in pad["results"]}, 0, 0
            for item in json.loads(result.output):
                if item["url"] in known:
                    continue
                known.add(item["url"])
                ok = in_window(item.get("date", ""))
                pad["results"].append({**item, "id": f"R{len(pad['results']) + 1}", "step": step.id,
                                       "in_window": ok, "origin": result.meta.get("source", "live")})
                added, fresh = added + 1, fresh + ok
            self.emit(state, event="evidence", step=step.id, new=added, in_window=fresh,
                      total=len(pad["results"]))
        elif step.tool == "calculator":
            pad.setdefault("calculations", []).append({"step": step.id, "expression": step.args.get("expression"),
                                                       "value": result.output})
        elif step.tool == REASON:
            data = json.loads(result.output)
            pad["findings"], pad["reason_notes"] = data.get("findings", []), data.get("notes", "")
