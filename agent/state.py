"""Data models: what the agent remembers during a run."""
from dataclasses import dataclass, field


@dataclass
class Step:
    id: int
    description: str              # what to do
    tool: str                     # which tool to call
    args: dict                    # arguments for the tool
    rationale: str                # WHY this step (goes into the final report)
    depends_on: list[int] = field(default_factory=list)
    bind_at_runtime: bool = False # args filled during execution, from earlier results
    status: str = "pending"       # pending | done | failed | skipped
    attempts: int = 0
    observation: str | None = None
    feedback: str = ""            # critic's complaint, given to the LLM on the next attempt


@dataclass
class RunState:
    goal: str
    plan: list[Step] = field(default_factory=list)
    interpretation: str = ""     # how the planner understood the goal
    assumptions: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)      # every tool call, result and verdict
    scratchpad: dict = field(default_factory=dict)          # facts gathered so far
    recoveries: list[dict] = field(default_factory=list)    # problem -> action -> outcome
    tool_calls: int = 0
    replans: int = 0
    llm_calls: int = 0
    stop_reason: str = ""          # why the run ended early, if it did
