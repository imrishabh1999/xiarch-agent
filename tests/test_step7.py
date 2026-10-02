import json

from agent.critic import numbers
from agent.report import build, confidence, render
from agent.trace import TraceLogger
from tests.test_step5 import FIX, run


def test_report_has_every_section_and_links(tmp_path):
    s = run(tmp_path)
    md = (tmp_path / "report.md").read_text()
    for section in ("## Goal and assumptions", "## Plan and what happened", "## Problems and recovery",
                    "## Findings", "## Evidence considered", "## Confidence and limitations", "## Run statistics"):
        assert section in md
    assert "**Status:** complete" in md and "https://example.com/mock/ss-pilot-line" in md
    assert "MOCK MODE" in md
    d = build(s)
    assert d["evidence_summary"]["excluded_stale"] == 1 and all(f["evidence"] for f in d["findings"])
    json.dumps(d)                                   # report must be JSON-serialisable


def test_failed_run_report_says_so(tmp_path):
    s = run(tmp_path, inject=["search:error:all"])
    d = build(s)
    assert d["status"].startswith("failed") and not d["findings"]
    assert "No findings could be verified" in render(d)


def test_confidence_rules():
    live = lambda src: {"origin": "live", "source": src, "url": ""}
    assert confidence([live("a"), live("b")])[0] == "high"
    assert confidence([live("a")])[0] == "medium"
    assert confidence([live("a"), {"origin": "cache", "source": "b", "url": ""}])[0] == "low"


def test_invented_number_is_rejected(tmp_path):
    fx = json.loads(json.dumps(FIX))
    bad = json.loads(json.dumps(fx["reason"]))
    bad["findings"][1]["summary"] = "Electrolyte ran 5,000 cycles."       # evidence says 1,000
    fx["reason"] = [bad, fx["reason"]]
    s = run(tmp_path, fixtures=fx)
    assert "5000" in s.recoveries[0]["problem"] and s.scratchpad["status"] == "complete"


def test_numbers_normalised():
    assert numbers("1,000 cycles and 2.5 GWh") == {"1000", "2.5"}


def test_trace_written_as_jsonl(tmp_path):
    log = TraceLogger(lambda e: None, root=tmp_path)
    log({"event": "a"}); log({"event": "b"}); log.close()
    lines = (log.dir / "trace.jsonl").read_text().splitlines()
    assert [json.loads(x)["event"] for x in lines] == ["a", "b"]
