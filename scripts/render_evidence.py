#!/usr/bin/env python3
"""Render captured CLI output as PNG evidence screenshots.

The application in this repository is a CLI/Lambda service with no web UI.
These screenshots are generated from the *actual* stdout/stderr logs saved under
``docs/evidence``; the renderer only adds a title and terminal-style framing.  It
does not invent, edit, or summarize application output.

Usage:
    python scripts/render_evidence.py

Requires Google Chrome (set CHROME_BIN to override the default macOS path).
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"
SCREENSHOTS = EVIDENCE / "screenshots"
RENDER_DIR = SCREENSHOTS / "_render"

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

SHOTS = [
    {
        "source": EVIDENCE / "test-results" / "demo-sample_foia_request.txt",
        "output": "demo-foia-workflow.png",
        "title": "FOIA request - full triage workflow (actual CLI output)",
        "command": "python -m agents.demo samples/sample_foia_request.txt",
        "width": 1440,
        "height": 1900,
    },
    {
        "source": EVIDENCE / "test-results" / "demo-sample_contract_memo.txt",
        "output": "demo-contract-routing.png",
        "title": "Contract memo - SBU type-default routing + human review (actual CLI output)",
        "command": "python -m agents.demo samples/sample_contract_memo.txt",
        "width": 1440,
        "height": 1900,
    },
    {
        "source": EVIDENCE / "test-results" / "pytest.txt",
        "output": "test-suite-results.png",
        "title": "Automated test suite and coverage (actual pytest output)",
        "command": "python -m pytest tests/ -v --cov=agents --cov=workflows",
        "width": 1500,
        "height": 2400,
    },
    {
        "source": EVIDENCE / "build-results" / "docker-run.txt",
        "output": "docker-container-run.png",
        "title": "Production container - demo workflow (actual docker run output)",
        "command": "docker run --rm federal-doc-triage-agent:audit",
        "width": 1440,
        "height": 1500,
    },
    {
        "source": EVIDENCE / "test-results" / "smoke.txt",
        "output": "smoke-checks.png",
        "title": "Local smoke checks (actual CLI output, no AWS calls)",
        "command": "python test_local.py",
        "width": 1440,
        "height": 1400,
    },
    {
        "source": EVIDENCE / "test-results" / "demo-sample_foia_request.txt",
        "output": "demo-foia-narrow.png",
        "title": "Narrow viewport (430 px) - CLI output remains readable",
        "command": "python -m agents.demo samples/sample_foia_request.txt",
        "width": 430,
        "height": 2400,
        "narrow": True,
    },
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    found = shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    raise SystemExit(
        "Google Chrome/Chromium not found. Set CHROME_BIN to an executable path."
    )


def render_html(shot: dict) -> Path:
    source: Path = shot["source"]
    text = source.read_text(encoding="utf-8", errors="replace")
    body = html.escape(text)
    title = html.escape(shot["title"])
    command = html.escape(shot["command"])
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    narrow_css = (
        "pre { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-all; } "
        ".frame { width: 398px; }"
        if shot.get("narrow")
        else "pre { white-space: pre; } .frame { width: 1320px; }"
    )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px; background: #11151c; color: #d7e0ea;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  .frame {{ max-width: calc(100vw - 48px); margin: 0 auto; }}
  h1 {{ font-size: 19px; line-height: 1.35; margin: 0 0 8px; color: #f4f7fb; }}
  .meta {{ font-size: 12px; color: #8fa3b8; margin-bottom: 14px; }}
  .meta code {{ color: #9be28f; }}
  .terminal {{
    background: #0b0f14; border: 1px solid #2b3644; border-radius: 8px;
    box-shadow: 0 12px 40px rgba(0,0,0,.35); overflow: hidden;
  }}
  .bar {{
    display: flex; align-items: center; gap: 7px; padding: 9px 13px;
    background: #171e27; border-bottom: 1px solid #2b3644;
  }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .red {{ background: #ff5f57; }} .yellow {{ background: #febc2e; }} .green {{ background: #28c840; }}
  .bar span {{ margin-left: 8px; font: 11px ui-monospace, Menlo, monospace; color: #8fa3b8; }}
  pre {{
    margin: 0; padding: 18px; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #d7e0ea; tab-size: 2;
  }}
  .note {{ margin-top: 10px; font-size: 11px; color: #8294a8; }}
  {narrow_css}
</style>
</head>
<body>
<div class="frame">
  <h1>{title}</h1>
  <div class="meta">Command: <code>{command}</code> &nbsp;|&nbsp; Captured: {generated} &nbsp;|&nbsp; Source: {html.escape(str(source.relative_to(ROOT)))}</div>
  <div class="terminal">
    <div class="bar"><i class="dot red"></i><i class="dot yellow"></i><i class="dot green"></i><span>federal-doc-triage-agent</span></div>
    <pre>{body}</pre>
  </div>
  <div class="note">Rendered directly from the captured stdout/stderr log shown above; no application output was altered.</div>
</div>
</body>
</html>"""

    target = RENDER_DIR / (shot["output"].replace(".png", ".html"))
    target.write_text(document, encoding="utf-8")
    return target


def main() -> int:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    for shot in SHOTS:
        if not shot["source"].exists():
            raise SystemExit(f"Missing evidence log: {shot['source']}")
        html_path = render_html(shot)
        output = SCREENSHOTS / shot["output"]
        command = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--user-data-dir={RENDER_DIR / 'chrome-profile'}",
            f"--window-size={shot['width']},{shot['height']}",
            f"--screenshot={output}",
            html_path.as_uri(),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode != 0 or not output.exists():
            raise SystemExit(
                f"Chrome render failed for {shot['output']}: {result.stderr[-500:]}"
            )
        print(f"wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
