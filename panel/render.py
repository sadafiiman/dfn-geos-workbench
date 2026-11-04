"""Tiny server-side HTML rendering helpers (no external template engine)."""

from __future__ import annotations

import html
import time


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def fmt_size(n: int | float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def layout(title: str, body: str, active: str = "") -> str:
    nav = [
        ("", "Dashboard"),
        ("quick", "Quick process"),
        ("settings", "Settings"),
        ("docs", "Guide"),
    ]
    nav_html = "".join(
        f'<a href="/{href}" class="{"active" if href == active else ""}">{esc(label)}</a>'
        for href, label in nav)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · dfn–GEOS Workbench</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header>
  <div class="brand"><span class="logo">▦</span> dfn–GEOS Workbench</div>
  <nav>{nav_html}</nav>
</header>
<main>
{body}
</main>
<footer>dfnWorks ↔ GEOS integration panel · cross-platform (Ubuntu & Windows)</footer>
<script src="/static/app.js"></script>
</body>
</html>"""


STATUS_BADGE = {
    "queued": "badge badge-queued",
    "running": "badge badge-running",
    "done": "badge badge-done",
    "failed": "badge badge-failed",
    "canceled": "badge badge-queued",
}


def job_row(j) -> str:
    badge = STATUS_BADGE.get(j["status"], "badge")
    dur = ""
    if j["started_at"]:
        end = j["ended_at"] or time.time()
        dur = f"{end - j['started_at']:.0f}s"
    return f"""<tr>
  <td>#{j['id']}</td>
  <td><code>{esc(j['stage'])}</code></td>
  <td><span class="{badge}">{esc(j['status'])}</span></td>
  <td>{esc(j['backend'])}</td>
  <td>{fmt_ts(j['created_at'])}</td>
  <td>{dur}</td>
  <td class="actions">
    <a href="/job/{j['id']}">log</a>
    {f'<button data-cancel="{j["id"]}" class="link-btn">cancel</button>'
     if j['status'] in ('queued', 'running') else ''}
  </td>
</tr>"""


def stage_button(case_id: int, stage: str, label: str, subtitle: str) -> str:
    return f"""<form method="post" action="/case/{case_id}/run" class="stage">
  <input type="hidden" name="stage" value="{esc(stage)}">
  <button type="submit"><strong>{esc(label)}</strong><small>{esc(subtitle)}</small></button>
</form>"""
