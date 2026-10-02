"""Wraps a tool and makes it fail on purpose, controlled by the CLI.
Spec format: <tool>:<failure>[:<count>]   e.g. search:timeout:1, search:garbage, calc:error:all
count = how many calls fail (default 1); 'all' = every call."""
from agent.tools.base import Tool, ToolResult

ALIASES = {"search": "web_search", "calc": "calculator", "write": "write_file"}
FAILURES = {"timeout", "empty", "garbage", "error"}


def parse_spec(spec: str) -> tuple[str, str, int]:
    parts = spec.split(":")
    if len(parts) not in (2, 3) or parts[1] not in FAILURES:
        raise ValueError(f"bad --inject '{spec}'. Use tool:failure[:count], failure in {sorted(FAILURES)}")
    tool = ALIASES.get(parts[0], parts[0])
    count = 10**9 if len(parts) == 3 and parts[2] == "all" else int(parts[2]) if len(parts) == 3 else 1
    return tool, parts[1], count


class FaultInjector(Tool):
    def __init__(self, inner: Tool, failure: str, count: int = 1):
        self.inner, self.failure, self.remaining = inner, failure, count
        self.name, self.description, self.schema = inner.name, inner.description, inner.schema
        self.injected = 0

    def run(self, **args) -> ToolResult:
        if self.remaining <= 0:
            return self.inner.run(**args)
        self.remaining -= 1
        self.injected += 1
        meta = {"injected": self.failure}
        if self.failure == "timeout":
            return ToolResult(ok=False, output="", error="timeout: injected - tool did not respond in time", meta=meta)
        if self.failure == "error":
            return ToolResult(ok=False, output="", error="http_500: injected - upstream server error", meta=meta)
        if self.failure == "empty":
            return ToolResult(ok=True, output="[]", meta={**meta, "count": 0})
        return ToolResult(ok=True, output="<html>\u00bf\u00bf unexpected markup {not json", meta=meta)  # garbage


def apply_injections(tools: list[Tool], specs: list[str]) -> list[Tool]:
    out = []
    for t in tools:
        for spec in specs:
            name, failure, count = parse_spec(spec)
            if name == t.name:
                t = FaultInjector(t, failure, count)
        out.append(t)
    return out
