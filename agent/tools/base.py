"""One interface for every tool, plus a router that validates arguments.
Tools never raise into the agent loop: every problem comes back as ToolResult(ok=False)."""
import time
from dataclasses import dataclass, field

PY_TYPES = {"string": str, "integer": int, "number": (int, float)}


@dataclass
class ToolResult:
    ok: bool
    output: str
    error: str | None = None
    meta: dict = field(default_factory=dict)    # latency, source, etc.


class Tool:
    name: str = ""
    description: str = ""
    schema: dict = {}       # {"arg": {"type": "string", "required": True}}

    def run(self, **args) -> ToolResult:
        raise NotImplementedError


class ToolRouter:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}

    def describe(self) -> list[dict]:
        """Tool list given to the planner so it knows what it can use."""
        return [{"name": t.name, "description": t.description, "args": t.schema} for t in self.tools.values()]

    def validate(self, name: str, args: dict) -> str | None:
        if name not in self.tools:
            return f"unknown tool '{name}'. Available: {list(self.tools)}"
        schema = self.tools[name].schema
        for arg, spec in schema.items():
            if spec.get("required") and arg not in args:
                return f"missing required argument '{arg}' for {name}"
            if arg in args and not isinstance(args[arg], PY_TYPES[spec["type"]]):
                return f"argument '{arg}' must be {spec['type']}, got {type(args[arg]).__name__}"
        extra = set(args) - set(schema)
        if extra:
            return f"unexpected arguments {sorted(extra)} for {name}"
        return None

    def call(self, name: str, args: dict) -> ToolResult:
        problem = self.validate(name, args)
        if problem:
            return ToolResult(ok=False, output="", error=f"invalid_args: {problem}")
        start = time.perf_counter()
        try:
            result = self.tools[name].run(**args)
        except Exception as e:  # last safety net; tools should already catch their own errors
            result = ToolResult(ok=False, output="", error=f"crash: {e}")
        result.meta["latency_s"] = round(time.perf_counter() - start, 3)
        return result
