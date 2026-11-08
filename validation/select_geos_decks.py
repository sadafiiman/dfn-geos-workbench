#!/usr/bin/env python3
"""Select the Task-1 requirements-critical GEOS decks from inputFiles.

A deck is in scope if it exercises external-mesh import (VTKMesh) or explicit
surface/fracture regions (SurfaceElementRegion / EmbeddedSurfaceGenerator).

Excluded:
  * fragments referenced by another deck via <Included>
  * decks without <Mesh> (pure include fragments)
  * decks whose external mesh file is absent from the tree
"""
from __future__ import annotations

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # integration workspace
GEOS = ROOT / "GEOS"
INPUTS = GEOS / "inputFiles"


def parse(path: Path):
    try:
        return ET.parse(path).getroot()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "geos-tests" / "selection.json"))
    args = ap.parse_args()

    decks = sorted(INPUTS.rglob("*.xml"))
    included: set[Path] = set()
    parsed: dict[Path, ET.Element] = {}
    for p in decks:
        root = parse(p)
        if root is None:
            continue
        parsed[p] = root
        for inc in root.iter("Included"):
            for f in re.findall(r"[^,\s{}/]+\.xml|[\w./-]+\.xml", inc.text or ""):
                included.add((p.parent / f).resolve())

    rows = []
    for p, root in parsed.items():
        text = p.read_text(errors="ignore")
        tags = {e.tag for e in root.iter()}
        has_mesh = "Mesh" in tags
        relevant = bool(tags & {"VTKMesh", "SurfaceElementRegion",
                                "EmbeddedSurfaceGenerator"})
        if not relevant or not has_mesh:
            continue
        if p.resolve() in included or p.stem.endswith("_base"):
            continue

        missing = []
        for e in root.iter():
            f = e.get("file")
            if f:
                ref = (p.parent / f).resolve()
                if not ref.exists():
                    missing.append(str(ref))
        rows.append({
            "deck": str(p.relative_to(INPUTS)),
            "category": p.relative_to(INPUTS).parts[0],
            "vtk_mesh": "VTKMesh" in tags,
            "surface_region": "SurfaceElementRegion" in tags,
            "embedded": "EmbeddedSurfaceGenerator" in tags,
            "internal_mesh": "InternalMesh" in tags,
            "missing_files": missing,
            "runnable": not missing,
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    runnable = [r for r in rows if r["runnable"]]
    print(f"candidates: {len(rows)}  runnable: {len(runnable)}  "
          f"missing data: {len(rows)-len(runnable)}")
    by_cat = {}
    for r in runnable:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
