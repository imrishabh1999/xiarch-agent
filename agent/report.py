"""Report generator: turns the run state into a structured JSON report and a readable Markdown report.
Honesty rules: findings come only from critic-approved reasoning; every finding shows its evidence links;
confidence and limitations are computed from facts about the run, not written by the LLM."""
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from agent.critic import requested_count
from agent.planner import REASON
from agent.state import RunState


def compute_status(state: RunState) -> str:
    findings = state.scratchpad.get("findings", [])
    partial = any(e.get("event") == "verdict" and str(e.get("reason", "")).startswith("partial")
                  for e in state.history)
    if not findings:
        return "failed: no verified findings"
    if partial or state.stop_reason:
        return "partial"
    return "complete"


def _source(r: dict) -> str:
    return (r.get("source") or urlparse(r.get("url", "")).netloc or "unknown").lower()


def confidence(evidence: list[dict]) -> tuple[str, str]:
    origins = {e["origin"] for e in evidence}
    sources = {_source(e) for e in evidence}
    if "cache" in origins:
        return "low", "relies on cached search results, which may be out of date"
    if len(sources) >= 2:
        return "high", f"reported by {len(sources)} independent sources"
    return "medium", "reported by a single source"


def build(state: RunState) -> dict:
    ev = {r["id"]: r for r in state.scratchpad.get("results", [])}
    findings = []
    for f in state.scratchpad.get("findings", []):
        cited = [ev[i] for i in f.get("evidence_ids", []) if i in ev]
        level, why = confidence(cited)
        findings.append({"title": f.get("title", ""), "summary": f.get("summary", ""),
                         "why_selected": f.get("why_selected", ""), "confidence": level, "confidence_reason": why,
                         "evidence": [{k: e.get(k) for k in ("id", "title", "url", "date", "source", "origin", "snippet")}
                                      for e in cited]})
    results = list(ev.values())
    stale = [r for r in results if not r["in_window"]]
    status = compute_status(state)
    origins = {r["origin"] for r in results}
    need = requested_count(state.goal)

    limitations = ["Findings are based on search headlines and snippets, not on reading full articles.",
                   "Which developments count as 'top' is the model's judgement over the evidence, "
                   "using the criteria listed under Assumptions."]
    if "mock" in origins:
        limitations.insert(0, "MOCK MODE: all search results and model replies are synthetic test data.")
    if "live" in origins:
        limitations.append("Live news search results change between runs, so a rerun may differ.")
    if need and len(findings) < need:
        limitations.append(f"Only {len(findings)} of the {need} requested developments are supported by the "
                           f"evidence; the agent did not pad the list.")
    if stale:
        limitations.append(f"{len(stale)} result(s) dated outside the 7-day window (or undated) were excluded.")
    if "cache" in origins:
        limitations.append("Some evidence came from cached results of an earlier live search.")
    if state.stop_reason:
        limitations.append(f"The run stopped early: {state.stop_reason}.")
    if not findings:
        limitations.append("No finding could be verified, so none is reported.")

    return {
        "goal": state.goal, "status": status, "interpretation": state.interpretation,
        "assumptions": state.assumptions,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plan": [{"id": s.id, "tool": s.tool, "description": s.description, "rationale": s.rationale,
                  "depends_on": s.depends_on, "status": s.status, "attempts": s.attempts} for s in state.plan],
        "recoveries": state.recoveries,
        "findings": findings,
        "reason_notes": state.scratchpad.get("reason_notes", ""),
        "evidence_summary": {"collected": len(results), "in_window": len(results) - len(stale),
                             "excluded_stale": len(stale), "origins": sorted(origins)},
        "calculations": state.scratchpad.get("calculations", []),
        "limitations": limitations,
        "stats": {"tool_calls": state.tool_calls, "llm_calls": state.llm_calls, "replans": state.replans,
                  "recoveries": len(state.recoveries),
                  "duration_s": state.history[-1]["t"] if state.history else 0},
    }


def render(d: dict) -> str:
    L = [f"# Research report: {d['goal']}", "",
         f"**Status:** {d['status']}  |  **Generated:** {d['generated_at']}", "",
         "## Goal and assumptions", f"Understood as: {d['interpretation']}", ""]
    L += [f"- {a}" for a in d["assumptions"]] + [""]

    L += ["## Plan and what happened", "", "| # | Tool | Step | Why | Result |", "|---|---|---|---|---|"]
    for s in d["plan"]:
        tries = f" ({s['attempts']} attempts)" if s["attempts"] > 1 else ""
        st = "writing this report" if s["tool"] == "write_file" and s["status"] == "pending" else s["status"]
        L.append(f"| {s['id']} | {s['tool']} | {s['description']} | {s['rationale']} | {st}{tries} |")
    L.append("")

    L += ["## Problems and recovery", ""]
    if d["recoveries"]:
        for r in d["recoveries"]:
            L.append(f"- Step {r['step']}, attempt {r['attempt']}: {r['problem']} → **{r['action']}** "
                     f"({r.get('outcome', 'pending')})")
    else:
        L.append("- No problems occurred.")
    L.append("")

    L += ["## Findings", ""]
    if not d["findings"]:
        L.append("No findings could be verified against the evidence, so none are reported.")
    for n, f in enumerate(d["findings"], 1):
        L += [f"### {n}. {f['title']}", f["summary"], "",
              f"*Why selected:* {f['why_selected']}  ",
              f"*Confidence:* **{f['confidence']}** ({f['confidence_reason']})", "", "Sources:"]
        L += [f"- [{e['title'] or e['url']}]({e['url']}): {e['source']}, {e['date']}"
              + (" (cached)" if e["origin"] == "cache" else "") for e in f["evidence"]]
        L.append("")
    if d["reason_notes"]:
        L += [f"*Analyst notes:* {d['reason_notes']}", ""]

    es = d["evidence_summary"]
    L += ["## Evidence considered",
          f"{es['collected']} unique results collected, {es['in_window']} inside the 7-day window, "
          f"{es['excluded_stale']} excluded as stale or undated. Origin: {', '.join(es['origins']) or 'none'}.", ""]
    for c in d["calculations"]:
        L.append(f"- Calculation (step {c['step']}): `{c['expression']}` = {c['value']}")
    L += ["", "## Confidence and limitations"] + [f"- {x}" for x in d["limitations"]] + [""]
    s = d["stats"]
    L += ["## Run statistics",
          f"Tool calls: {s['tool_calls']} | LLM calls: {s['llm_calls']} | Recoveries: {s['recoveries']} | "
          f"Replans: {s['replans']} | Duration: {s['duration_s']}s"]
    return "\n".join(L)


def markdown_report(state: RunState) -> str:
    return render(build(state))
