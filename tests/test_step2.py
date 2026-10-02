import json

import pytest

from agent.tools.base import ToolRouter
from agent.tools.calculator import Calculator
from agent.tools.fault_injection import apply_injections, parse_spec
from agent.tools.web_search import WebSearch
from agent.tools.write_file import WriteFile


def test_mock_search_returns_dated_results():
    r = WebSearch(backend="mock").run(query="solid-state battery news")
    data = json.loads(r.output)
    assert r.ok and len(data) == 5 and all(d["date"] and d["url"] for d in data)


def test_mock_search_unknown_topic_is_empty_not_error():
    r = WebSearch(backend="mock").run(query="underwater basket weaving")
    assert r.ok and json.loads(r.output) == []


def test_live_search_failure_becomes_error_result(monkeypatch):
    import ddgs
    from ddgs.exceptions import TimeoutException

    class Boom:
        def __init__(self, **kw): pass
        def news(self, *a, **kw): raise TimeoutException("timed out")
    monkeypatch.setattr(ddgs, "DDGS", Boom)
    r = WebSearch(backend="live").run(query="anything")
    assert not r.ok and r.error.startswith("timeout")


def test_write_file_blocks_path_traversal(tmp_path):
    w = WriteFile(out_dir=tmp_path)
    assert not w.run(path="../evil.txt", content="x").ok
    assert not w.run(path="/etc/evil", content="x").ok
    assert w.run(path="report.md", content="hello").ok and (tmp_path / "report.md").read_text() == "hello"


@pytest.mark.parametrize("failure, ok, check", [
    ("timeout", False, lambda r: r.error.startswith("timeout")),
    ("error", False, lambda r: r.error.startswith("http_500")),
    ("empty", True, lambda r: r.output == "[]"),
    ("garbage", True, lambda r: not r.output.startswith("[")),
])
def test_injected_failures(failure, ok, check):
    router = ToolRouter(apply_injections([WebSearch(backend="mock")], [f"search:{failure}:1"]))
    r = router.call("web_search", {"query": "solid-state battery"})
    assert r.ok == ok and check(r) and r.meta["injected"] == failure
    r2 = router.call("web_search", {"query": "solid-state battery"})   # count=1: second call is normal
    assert r2.ok and len(json.loads(r2.output)) == 5


def test_inject_all_keeps_failing():
    router = ToolRouter(apply_injections([Calculator()], ["calc:error:all"]))
    assert not router.call("calculator", {"expression": "1+1"}).ok
    assert not router.call("calculator", {"expression": "1+1"}).ok


def test_bad_spec_rejected():
    with pytest.raises(ValueError):
        parse_spec("search:explode")


def test_live_search_skips_bing_and_falls_back_to_yahoo(monkeypatch):
    import ddgs
    calls = []

    class Fake:
        def __init__(self, **kw): pass
        def news(self, query, backend, **kw):
            calls.append(backend)
            if backend == "duckduckgo":
                raise RuntimeError("ratelimited")
            return [{"title": "t", "url": "u", "body": "b", "date": "2026-10-01T10:00:00+00:00", "source": "s"}]
    monkeypatch.setattr(ddgs, "DDGS", Fake)
    r = WebSearch(backend="live").run(query="anything")
    assert r.ok and r.meta["engine"] == "yahoo" and calls == ["duckduckgo", "yahoo"] and "bing" not in calls
