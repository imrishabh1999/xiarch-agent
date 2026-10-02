"""Write text files, sandboxed to the outputs/ directory (no path traversal, no absolute paths)."""
from pathlib import Path

from agent.tools.base import Tool, ToolResult

OUT_DIR = Path(__file__).resolve().parents[2] / "outputs"


class WriteFile(Tool):
    name = "write_file"
    description = "Save text to a file inside outputs/. Path must be relative, e.g. 'report.md'."
    schema = {"path": {"type": "string", "required": True}, "content": {"type": "string", "required": True}}

    def __init__(self, out_dir: Path = OUT_DIR):
        self.out_dir = out_dir.resolve()

    def run(self, path: str, content: str) -> ToolResult:
        target = (self.out_dir / path).resolve()
        if Path(path).is_absolute() or self.out_dir not in target.parents:
            return ToolResult(ok=False, output="", error=f"rejected: '{path}' is outside outputs/")
        if len(content) > 200_000:
            return ToolResult(ok=False, output="", error="rejected: content too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult(ok=True, output=f"wrote {len(content)} chars to outputs/{path}")
