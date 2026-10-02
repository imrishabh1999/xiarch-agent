"""Web search tool. Backends:
- live: DuckDuckGo news via the free `ddgs` package (no API key), with a timeout.
- mock: deterministic results from data/mock_search.json, for reviewers without internet.
Successful live results are cached; recovery can fall back to the cache (clearly labelled as cached)."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.tools.base import Tool, ToolResult

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / ".cache" / "search"
MOCK_FILE = ROOT / "data" / "mock_search.json"
ENGINES = ("duckduckgo", "yahoo")   # deliberately not bing: see run()


def _norm_date(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return ""


def _cache_path(query: str) -> Path:
    return CACHE_DIR / (hashlib.sha1(query.lower().strip().encode()).hexdigest()[:16] + ".json")


def cache_lookup(query: str) -> ToolResult:
    p = _cache_path(query)
    if not p.exists():
        return ToolResult(ok=False, output="", error="cache_miss: no cached results for this query")
    data = json.loads(p.read_text(encoding="utf-8"))
    return ToolResult(ok=True, output=json.dumps(data["results"]),
                      meta={"source": "cache", "cached_at": data["cached_at"], "count": len(data["results"])})


class WebSearch(Tool):
    name = "web_search"
    description = ("Search recent news. Returns a JSON list of {title, url, snippet, date, source}. "
                   "Results are already limited to the last 7 days; keep queries short, no dates.")
    schema = {"query": {"type": "string", "required": True},
              "max_results": {"type": "integer", "required": False}}

    def __init__(self, backend: str = "live", timeout: int = 10):
        self.backend = backend
        self.timeout = timeout

    def run(self, query: str, max_results: int = 5) -> ToolResult:
        max_results = max(1, min(max_results, 10))
        if self.backend == "mock":
            return self._mock(query, max_results)
        # Engine order matters: ddgs' Bing parser turns dates like "Sep 25" into "25 days ago",
        # which made fresh news look stale. DuckDuckGo returns ISO dates; Yahoo parses "2 days ago".
        from ddgs import DDGS
        raw, engine, errors = None, None, []
        for engine in ENGINES:
            try:
                raw = DDGS(timeout=self.timeout).news(query, timelimit="w", max_results=max_results, backend=engine)
            except Exception as e:  # ddgs raises its own Timeout/Ratelimit exceptions
                errors.append(e)
                continue
            if raw:
                break
        if raw is None:
            e = errors[-1]
            timeout = any("timeout" in type(x).__name__.lower() or "timed out" in str(x).lower() for x in errors)
            return ToolResult(ok=False, output="", error=f"{'timeout' if timeout else 'search_error'}: {e}")
        results = [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("body", ""),
                    "date": _norm_date(r.get("date", "")), "source": r.get("source", "")} for r in raw]
        if results:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _cache_path(query).write_text(json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(),
                                                      "results": results}), encoding="utf-8")
        return ToolResult(ok=True, output=json.dumps(results),
                          meta={"source": "live", "engine": engine, "count": len(results)})

    def _mock(self, query: str, max_results: int) -> ToolResult:
        q = query.lower()
        topics = json.loads(MOCK_FILE.read_text(encoding="utf-8"))["topics"]
        today = datetime.now(timezone.utc).date()
        for t in topics:
            if any(k in q for k in t["keywords"]):
                results = [{"title": r["title"], "url": r["url"], "snippet": r["snippet"], "source": r["source"],
                            "date": (today - timedelta(days=r["days_ago"])).isoformat()}
                           for r in t["results"][:max_results]]
                return ToolResult(ok=True, output=json.dumps(results), meta={"source": "mock", "count": len(results)})
        return ToolResult(ok=True, output="[]", meta={"source": "mock", "count": 0})
