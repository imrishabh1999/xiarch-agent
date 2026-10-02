"""LLM access. GroqLLM talks to the Groq API; MockLLM returns canned answers from a JSON file,
so the agent runs with no key and no internet (--mock) and tests are deterministic."""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "openai/gpt-oss-120b"


class LLMError(Exception):
    pass


def parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in ``` fences or add a sentence around it; take the outer {...}."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start:end + 1])


class LLM:
    def __init__(self):
        self.calls = 0

    def complete(self, system: str, user: str, stage: str) -> str:
        raise NotImplementedError


class GroqLLM(LLM):
    def __init__(self, model: str | None = None):
        super().__init__()
        from dotenv import load_dotenv
        from groq import Groq
        load_dotenv(ROOT / ".env")
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise LLMError("GROQ_API_KEY is not set. Add it to .env, or run with --mock.")
        self.model = model or os.getenv("GROQ_MODEL") or DEFAULT_MODEL
        self.client = Groq(api_key=key, timeout=60, max_retries=2)

    def complete(self, system: str, user: str, stage: str) -> str:
        self.calls += 1
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.2,
                response_format={"type": "json_object"})
        except Exception as e:
            if "response_format" not in str(e) and "json" not in str(e).lower():
                raise LLMError(f"{type(e).__name__}: {e}") from e
            try:  # some models reject JSON mode; ask again without it, parse_json copes
                resp = self.client.chat.completions.create(model=self.model, messages=messages, temperature=0.2)
            except Exception as e2:
                raise LLMError(f"{type(e2).__name__}: {e2}") from e2
        return resp.choices[0].message.content or ""


class MockLLM(LLM):
    """fixtures: {stage: response} or {stage: [response1, response2, ...]} (consumed in order)."""

    def __init__(self, fixtures: dict | None = None, path: Path = ROOT / "data" / "mock_llm.json"):
        super().__init__()
        self.fixtures = fixtures if fixtures is not None else json.loads(path.read_text(encoding="utf-8"))
        self.seen: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, stage: str) -> str:
        self.calls += 1
        self.seen.append((stage, user))
        item = self.fixtures.get(stage)
        if item is None:
            raise LLMError(f"mock has no response for stage '{stage}'")
        if isinstance(item, list):
            item = item.pop(0) if len(item) > 1 else item[0]
        return item if isinstance(item, str) else json.dumps(item)


if __name__ == "__main__" and "--list-models" in sys.argv:
    llm = GroqLLM()
    for m in sorted(m.id for m in llm.client.models.list().data):
        print(m)
