"""Critic: judges every result BEFORE the agent trusts it. All checks are deterministic code,
so the critic cannot repeat the LLM's mistakes. Verdict = (passed, "category: reason")."""
import json
import re
from datetime import date, timedelta

from agent.planner import REASON
from agent.state import RunState, Step
from agent.tools.base import ToolResult

WINDOW_DAYS = 7
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def in_window(d: str, today: date | None = None) -> bool:
    today = today or date.today()
    try:
        day = date.fromisoformat(d)
    except (TypeError, ValueError):
        return False                       # undated news cannot be verified as recent
    return today - timedelta(days=WINDOW_DAYS) <= day <= today + timedelta(days=1)  # +1: timezone slack


def requested_count(goal: str) -> int | None:
    m = re.search(r"\btop\s+(\d+|one|two|three|four|five)\b", goal.lower())
    if not m:
        return None
    return int(m.group(1)) if m.group(1).isdigit() else WORDS[m.group(1)]


def numbers(text: str) -> set[str]:
    """Numbers in a text, '1,000' and '1000' treated alike. Used to catch invented figures."""
    return set(re.findall(r"\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d{3})", "", text or "")))


class Critic:
    def check(self, step: Step, result: ToolResult, state: RunState, final_attempt: bool = False) -> tuple[bool, str]:
        if not result.ok:
            return False, result.error or "error: tool reported failure"
        if step.tool == "web_search":
            return self.check_search(result)
        if step.tool == REASON:
            return self.check_findings(result, state, final_attempt)
        return True, "ok"

    def check_search(self, result: ToolResult) -> tuple[bool, str]:
        try:
            items = json.loads(result.output)
        except ValueError:
            return False, "malformed: search output is not valid JSON"
        if not isinstance(items, list) or not all(isinstance(i, dict) and i.get("url") for i in items):
            return False, "malformed: search output is not a list of results with URLs"
        if not items:
            return False, "empty: search returned no results"
        fresh = sum(in_window(i.get("date", "")) for i in items)
        if fresh == 0:
            undated = sum(not i.get("date") for i in items)
            return False, (f"stale: none of {len(items)} results is dated within the last {WINDOW_DAYS} days"
                           + (f" ({undated} undated)" if undated else ""))
        return True, f"ok: {fresh}/{len(items)} results inside the {WINDOW_DAYS}-day window"

    def check_findings(self, result: ToolResult, state: RunState, final_attempt: bool) -> tuple[bool, str]:
        """Every finding must cite real, in-window evidence; no evidence reused; enough findings."""
        try:
            findings = json.loads(result.output).get("findings")
        except (ValueError, AttributeError):
            return False, "malformed: reasoning output is not the expected JSON"
        if not isinstance(findings, list) or not findings:
            return False, "too_few: no findings returned"
        evidence = {r["id"]: r for r in state.scratchpad.get("results", [])}
        used = set()
        for f in findings:
            ids = f.get("evidence_ids") or []
            title = str(f.get("title", "?"))[:50]
            if not ids:
                return False, f"ungrounded: finding '{title}' cites no evidence"
            for i in ids:
                if i not in evidence:
                    return False, f"ungrounded: finding '{title}' cites {i}, which does not exist"
                if not evidence[i]["in_window"]:
                    return False, f"stale: finding '{title}' relies on {i}, dated {evidence[i]['date'] or 'unknown'}"
                if i in used:
                    return False, f"duplicate: {i} is used by more than one finding"
                used.add(i)
            cited_text = " ".join(f"{evidence[i].get('title', '')} {evidence[i].get('snippet', '')}" for i in ids)
            missing = [n for n in numbers(f"{f.get('title', '')} {f.get('summary', '')}") if n not in numbers(cited_text)]
            if missing:
                return False, (f"ungrounded: finding '{title}' states {', '.join(missing)}, "
                               f"which does not appear in its cited evidence")
        need = requested_count(state.goal)
        if need and len(findings) < need:
            if not final_attempt:
                return False, f"too_few: {len(findings)} findings, goal asks for {need}"
            return True, f"partial: only {len(findings)} of {need} findings are supported by the evidence"
        return True, f"ok: {len(findings)} findings, all cite in-window evidence"
