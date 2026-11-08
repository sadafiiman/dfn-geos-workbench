#!/usr/bin/env python3
"""Render ``docs/TUTORIAL_windows.md`` to ``docs/TUTORIAL_windows.pdf``.

Pipeline: markdown (small subset) -> styled HTML -> headless Chrome print.
No third-party Python packages; Chrome/Chromium must be on PATH.

    python docs/build_tutorial_pdf.py [--keep-html]
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
SRC = DOCS / "TUTORIAL_windows.md"
OUT = DOCS / "TUTORIAL_windows.pdf"

CSS = """
@page { size: A4; margin: 16mm 15mm 15mm 15mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
       font-size: 10pt; line-height: 1.4; color: #1c2733; margin: 0; }
h1 { font-size: 20pt; color: #0b4f6c; margin: 0 0 2mm 0;
     border-bottom: 2px solid #0b4f6c; padding-bottom: 2mm; }
h2 { font-size: 14pt; color: #0b4f6c; margin: 5.5mm 0 1.8mm 0;
     page-break-after: avoid; }
h3 { font-size: 11pt; color: #16697a; margin: 5mm 0 1.5mm 0;
     page-break-after: avoid; }
p { margin: 0 0 2mm 0; }
ul, ol { margin: 0 0 2.5mm 0; padding-left: 6mm; }
li { margin: 0 0 1.2mm 0; }
code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 9.3pt;
       background: #eef2f5; padding: 0.3mm 1.2mm; border-radius: 1.5mm;
       color: #a3331c; }
pre { background: #f4f6f8; border: 1px solid #dbe3e8; border-left: 3px solid
      #0b4f6c; border-radius: 1.5mm; padding: 2.5mm 3mm; margin: 0 0 3mm 0;
      page-break-inside: avoid; }
pre code { background: none; color: #1c2733; padding: 0; font-size: 9pt;
           line-height: 1.35; }
table { border-collapse: collapse; width: 100%; margin: 0 0 3mm 0;
        font-size: 9pt; page-break-inside: avoid; }
th { background: #0b4f6c; color: #fff; text-align: left; padding: 1.6mm 2mm;
     font-weight: 600; }
td { border-bottom: 1px solid #dbe3e8; padding: 1.5mm 2mm; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafb; }
blockquote { margin: 0 0 3mm 0; padding: 2mm 3mm; background: #eef7f2;
             border-left: 3px solid #2e7d5b; color: #1f4636; border-radius: 1mm; }
hr { border: none; border-top: 1px solid #dbe3e8; margin: 4mm 0; }
a { color: #0b6fa4; text-decoration: none; }
.lead { color: #45596b; font-size: 10pt; }
"""

CODE_HINT = {"bat": "PowerShell / cmd", "bash": "bash", "json": "JSON"}


def inline(text: str) -> str:
    """Escape and apply the inline markdown we use (code spans first)."""
    codes: list[str] = []

    def stash(match: re.Match) -> str:
        codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])",
                  r"<em>\1</em>", text)
    text = re.sub(r"&lt;(https?://[^&\s]+)&gt;", r'<a href="\1">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def table_html(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    out = ["<table><thead><tr>"]
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def convert(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    in_list = None

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            close_list()
            lang = stripped[3:].strip()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            label = CODE_HINT.get(lang)
            if label:
                out.append(f'<div class="lead">{label}</div>')
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            continue

        if stripped == "---":
            close_list()
            out.append("<hr/>")
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and set(
                lines[i + 1].strip()) <= set("|-: "):
            close_list()
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(table_html(rows))
            continue

        if stripped.startswith(">"):
            close_list()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m:
            if in_list != "ol":
                close_list()
                start = m.group(1)
                attr = "" if start == "1" else f' start="{start}"'
                out.append(f"<ol{attr}>")
                in_list = "ol"
            out.append(f"<li>{inline(m.group(2))}</li>")
            i += 1
            continue

        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            if in_list != "ul":
                close_list()
                out.append("<ul>")
                in_list = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        if not stripped:
            close_list()
            i += 1
            continue

        # continuation line of the current list item
        if in_list and out and out[-1].endswith("</li>"):
            out[-1] = out[-1][:-5] + " " + inline(stripped) + "</li>"
            i += 1
            continue

        close_list()
        # join until a blank line or a block start
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "|", ">", "```", "- ", "* "))
                    or re.match(r"^\d+\.\s", nxt) or nxt == "---"):
                break
            buf.append(nxt)
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")
    close_list()
    return "\n".join(out)


def find_chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "microsoft-edge", "msedge"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("Chrome/Chromium not found on PATH")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-html", action="store_true")
    args = ap.parse_args()

    body = convert(SRC.read_text(encoding="utf-8"))
    page = (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>dfnWorks → GEOS Workbench — Windows tutorial</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")

    tmp = Path(tempfile.mkdtemp(prefix="tutorial-"))
    html_path = tmp / "tutorial.html"
    html_path.write_text(page, encoding="utf-8")
    if args.keep_html:
        keep = DOCS / "TUTORIAL_windows.html"
        keep.write_text(page, encoding="utf-8")
        print(f"html  {keep}")

    chrome = find_chrome()
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--no-pdf-header-footer", "--virtual-time-budget=8000",
           f"--print-to-pdf={OUT}", html_path.as_uri()]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not OUT.exists():
        sys.stderr.write(proc.stderr[-2000:])
        return 1
    pages = OUT.read_bytes().count(b"/Type /Page") - OUT.read_bytes().count(
        b"/Type /Pages")
    print(f"pdf   {OUT}  ({OUT.stat().st_size / 1024:.0f} KiB, {pages} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
