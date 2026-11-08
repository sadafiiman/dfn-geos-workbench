#!/usr/bin/env python3
"""Map every GEOS sample deck to the Task-1 requirements.

Static facts are extracted from the deck (following <Included> fragments) and
combined with the empirical run status from geos-tests/results.jsonl.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GEOS = ROOT / "GEOS"
INPUTS = GEOS / "inputFiles"
WORK = ROOT / "geos-tests"
SELECTION = WORK / "selection.json"
RESULTS = WORK / "results.jsonl"
OUT = HERE / "REQUIREMENTS.md"


def load(path: Path, seen=None) -> list[ET.Element]:
    """Parse a deck, recursively pulling in <Included> fragments."""
    seen = seen or set()
    if path in seen or not path.exists():
        return []
    seen.add(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    elems = [root]
    for inc in root.iter("Included"):
        for name in re.findall(r"[\w./-]+\.xml", inc.text or ""):
            elems += load((path.parent / name).resolve(), seen)
    return elems


def facts(deck: str) -> dict:
    path = INPUTS / deck
    elems = load(path)
    tags = set()
    for e in elems:
        tags.update(x.tag for x in e.iter())

    def attribute_containing(substr: str) -> bool:
        return any(substr in (v or "") for e in elems for x in e.iter()
                   for v in x.attrib.values())

    surf = []
    for e in elems:
        for x in e.iter("SurfaceElementRegion"):
            surf.append(x.get("subRegionType") or "faceElement")
    cell_regions = sum(1 for e in elems for _ in e.iter("CellElementRegion"))
    solvers = [x for e in elems for x in e.iter("Solvers")]
    targeted = " ".join(x.get("targetRegions", "") for s in solvers for x in s)

    return {
        "external_mesh": "VTKMesh" in tags,
        "face_element": "faceElement" in surf,
        "embedded": "embeddedElement" in surf or "EmbeddedSurfaceGenerator" in tags,
        "matrix_region": cell_regions > 0,
        "fracture_region": bool(surf),
        # a solver spanning a cell region and a surface region = fracture-matrix coupling
        "coupled": bool(surf) and cell_regions > 0 and
                   len(re.findall(r"\w+", targeted)) >= 2,
        "vtk_output": "VTK" in tags or "VTKHDF" in tags,
        "regions": len(surf) + cell_regions,
    }


def main() -> int:
    selection = {r["deck"]: r for r in json.loads(SELECTION.read_text())}
    runs = {}
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                runs[r["deck"]] = r

    rows = []
    for deck, sel in sorted(selection.items()):
        if not sel["runnable"]:
            continue
        f = facts(deck)
        run = runs.get(deck)
        f.update(deck=deck, category=sel["category"],
                 status=run["status"] if run else "not-run",
                 seconds=run["seconds"] if run else 0)
        rows.append(f)

    caps = [
        ("A. External VTK mesh import", "external_mesh"),
        ("B. Explicit fracture region", "fracture_region"),
        ("C. Conformal face elements", "face_element"),
        ("D. Embedded (EDFM/EFEM) elements", "embedded"),
        ("E. Rock-matrix region", "matrix_region"),
        ("F. Fracture-matrix coupling", "coupled"),
    ]

    lines = ["# Task-1 requirements coverage across GEOS `inputFiles`\n"]
    status = Counter(r["status"] for r in rows)
    lines.append(f"Decks analysed: **{len(rows)}** — "
                 + ", ".join(f"{k} {v}" for k, v in sorted(status.items())) + "\n")

    lines.append("## Capability matrix\n")
    lines.append("| Requirement | decks with it | passed | failed/other |")
    lines.append("|---|---|---|---|")
    for label, key in caps:
        have = [r for r in rows if r[key]]
        ok = sum(1 for r in have if r["status"] == "pass")
        lines.append(f"| {label} | {len(have)} | {ok} | {len(have) - ok} |")

    allreq = [r for r in rows
              if r["external_mesh"] and r["face_element"] and r["matrix_region"]
              and r["coupled"]]
    lines.append(f"| **All of A+C+E+F together** | {len(allreq)} | "
                 f"{sum(1 for r in allreq if r['status'] == 'pass')} | "
                 f"{sum(1 for r in allreq if r['status'] != 'pass')} |")

    lines.append("\n## Decks that exercise the decisive path "
                 "(external mesh + conformal fracture + matrix coupling)\n")
    lines.append("| deck | status | s | VTK | face | embedded | matrix |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in sorted(allreq, key=lambda x: (x["status"] != "pass", x["deck"])):
        mark = lambda b: "yes" if b else "–"
        lines.append(f"| `{r['deck']}` | {r['status']} | {r['seconds']:.0f} | "
                     f"{mark(r['external_mesh'])} | {mark(r['face_element'])} | "
                     f"{mark(r['embedded'])} | {mark(r['matrix_region'])} |")

    lines.append("\n## Per-category coverage\n")
    lines.append("| Category | decks | A extern | B fracture | C conformal | "
                 "D embedded | F coupled | pass |")
    lines.append("|---|---|---|---|---|---|---|---|")
    cats = defaultdict(list)
    for r in rows:
        cats[r["category"]].append(r)
    for cat in sorted(cats):
        rs = cats[cat]
        n = len(rs)
        lines.append(
            f"| {cat} | {n} | "
            f"{sum(r['external_mesh'] for r in rs)} | "
            f"{sum(r['fracture_region'] for r in rs)} | "
            f"{sum(r['face_element'] for r in rs)} | "
            f"{sum(r['embedded'] for r in rs)} | "
            f"{sum(r['coupled'] for r in rs)} | "
            f"{sum(r['status'] == 'pass' for r in rs)} |")

    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}: {len(rows)} decks, "
          f"{len(allreq)} on the decisive path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
