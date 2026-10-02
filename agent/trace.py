"""Structured logging: every event is printed for humans AND appended to runs/<id>/trace.jsonl
as it happens, so even a crashed run leaves a complete record up to the crash."""
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

RUNS = Path(__file__).resolve().parents[1] / "runs"


class TraceLogger:
    def __init__(self, show: Callable[[dict], None], root: Path = RUNS):
        base, n = datetime.now().strftime("%Y%m%d-%H%M%S"), 1
        self.dir = root / base
        while self.dir.exists():
            n += 1
            self.dir = root / f"{base}-{n}"
        self.dir.mkdir(parents=True)
        self.file = (self.dir / "trace.jsonl").open("a", encoding="utf-8")
        self.show = show

    def __call__(self, event: dict):
        self.file.write(json.dumps(event, default=str) + "\n")
        self.file.flush()
        self.show(event)

    def save(self, name: str, text: str):
        (self.dir / name).write_text(text, encoding="utf-8")

    def close(self):
        self.file.close()
