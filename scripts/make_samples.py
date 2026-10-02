"""Runs the three sample runs and puts them in one page: samples/sample_runs.html
Open that file in Chrome or Edge, press Ctrl+P, choose "Save as PDF".
python -m scripts.make_samples          (live)
python -m scripts.make_samples --mock   (offline, for a quick check)"""
import html
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNS = [
    ("Run 1: Normal run",
     "Find the top 3 developments in solid-state batteries from the last week", [],
     ["The plan is printed first, with the guesses the agent made and a reason for every step.",
      "Each search shows how many results were new and how many were from the last 7 days.",
      "Older results are thrown out before the LLM picks the findings.",
      "Every finding in the report links to its source."]),
    ("Run 2: Something breaks and the agent fixes it",
     "Find the top 3 developments in AI regulation from the last week", ["search:garbage:1"],
     ["The first search returns broken output, but the tool still says 'ok'.",
      "The critic catches it anyway (REJECT, malformed) and the agent tries again.",
      "The second try works and the run finishes normally.",
      "The report's 'Problems and recovery' section lists what went wrong and how it was fixed."]),
    ("Run 3: Nothing works, and the agent says so",
     "Find the top 3 developments in renewable energy from the last week", ["search:error:all"],
     ["Every search fails. Each one is tried 3 times, then the agent tries saved results.",
      "Steps that depend on the failed searches are skipped instead of running on nothing.",
      "The agent makes a new plan once (look for '!! replan'). That fails too.",
      "It still writes a report. The status is 'failed' and no findings are made up."]),
]


def main():
    mock = "--mock" in sys.argv
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    parts = []
    for title, goal, inject, notes in RUNS:
        cmd = [sys.executable, "-m", "agent.main", goal] + (["--mock"] if mock else [])
        for i in inject:
            cmd += ["--inject", i]
        print(f"running: {title}", flush=True)
        out = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        report = (ROOT / "outputs" / "report.md").read_text(encoding="utf-8")
        shown = "python -m agent.main \"" + goal + "\"" + (" --mock" if mock else "") + \
                "".join(f" --inject {i}" for i in inject)
        parts.append(f"""<section><h2>{html.escape(title)}</h2>
<p class="cmd"><code>{html.escape(shown)}</code></p>
<div class="notes"><b>What to look at</b><ul>{''.join(f'<li>{html.escape(n)}</li>' for n in notes)}</ul></div>
<h3>Console output</h3><pre>{html.escape(out.stdout + out.stderr)}</pre>
<h3>Report the agent wrote (outputs/report.md)</h3><pre>{html.escape(report)}</pre></section>""")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Sample runs</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:24px auto;color:#222}}
h1{{margin-bottom:4px}} h2{{border-bottom:2px solid #333;padding-bottom:4px;margin-top:0}}
pre{{background:#f6f6f6;padding:10px;font-size:10.5px;white-space:pre-wrap;word-break:break-word;border:1px solid #ddd}}
.notes{{background:#eef4ff;padding:8px 14px;border-left:4px solid #3b6fd8}} .cmd code{{font-size:12px}}
section{{page-break-before:always}} section:first-of-type{{page-break-before:auto}}
</style></head><body><h1>Research Agent: three sample runs</h1>
<p>Recorded {datetime.now():%d %b %Y, %H:%M} in {'mock' if mock else 'live'} mode
(live = real Groq LLM and real news search).</p>{''.join(parts)}</body></html>"""
    out_dir = ROOT / "samples"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "sample_runs.html").write_text(page, encoding="utf-8")
    print("saved samples/sample_runs.html -> open it in Chrome/Edge, Ctrl+P, Save as PDF")


if __name__ == "__main__":
    main()
