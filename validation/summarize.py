#!/usr/bin/env python3
"""Summarise validation/results.jsonl into a markdown compatibility matrix."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1] / "geos-tests"
RESULTS = WORK / "results.jsonl"
SELECTION = WORK / "selection.json"
LOGS = WORK / "logs"
OUT = HERE / "RESULTS.md"

MAX_ERROR_LINES = 14


def log_path(deck: str) -> Path:
    return LOGS / (deck.replace("/", "__") + ".log")


def real_error(deck: str, fallback: str) -> str:
    """Return the first ``***** Message`` block of the GEOS log.

    ``run_decks.py`` records the tail of the output, which is usually the
    MPI_ABORT boilerplate; the actionable line is further up in the log.
    """
    path = log_path(deck)
    if not path.exists():
        return fallback
    lines = path.read_text(errors="replace").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("***** Message"):
            start = i
    if start is None:
        for i, line in enumerate(lines):
            if "Error" in line or "Invalid value" in line:
                start = i
    if start is None:
        return fallback
    end = start + 1
    while end < len(lines) and not lines[end].startswith("***** StackTrace"):
        end += 1
    block = [l for l in lines[start:end] if l.strip()][:MAX_ERROR_LINES]
    return "\n".join(block) if block else fallback


def main() -> int:
    selection = {r["deck"]: r for r in json.loads(SELECTION.read_text())}
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    latest = {}
    for r in rows:
        latest[r["deck"]] = r
    rows = list(latest.values())

    counts = Counter(r["status"] for r in rows)
    by_cat = defaultdict(Counter)
    for r in rows:
        by_cat[selection[r["deck"]]["category"]][r["status"]] += 1

    lines = []
    lines.append("# GEOS inputFiles validation matrix\n")
    lines.append(f"Decks run: **{len(rows)}** · "
                 + " · ".join(f"{k}: **{v}**" for k, v in sorted(counts.items()))
                 + f" · wall time: {sum(r['seconds'] for r in rows)/60:.0f} min\n")
    lines.append("| Category | pass | fail | timeout | xml-error | missing-file |")
    lines.append("|---|---|---|---|---|---|")
    for cat in sorted(by_cat):
        c = by_cat[cat]
        lines.append(f"| {cat} | {c['pass']} | {c['fail']} | {c['timeout']} | "
                     f"{c['xml-error']} | {c['missing-file']} |")

    lines.append("\n## Failed / skipped decks\n")
    for r in sorted(rows, key=lambda x: (x["status"], x["deck"])):
        if r["status"] == "pass":
            continue
        lines.append(f"### `{r['deck']}` — {r['status']} (rc={r['rc']}, "
                     f"{r['seconds']}s)\n")
        lines.append(f"```\n{real_error(r['deck'], r['error'])}\n```\n")

    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}  ({len(rows)} decks, {counts.get('pass', 0)} passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
