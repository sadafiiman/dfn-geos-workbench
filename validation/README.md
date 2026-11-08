# GEOS sample-deck validation

This directory answers the question *"do the requirements hold across GEOS' own
sample inventory?"* — not just for the converted dfnWorks case.

## What it does

1. **`select_geos_decks.py`** — scans `GEOS/inputFiles/**/*.xml`, keeps decks
   that actually exercise the Task-1 surface (an external `VTKMesh`, a
   `SurfaceElementRegion`, or an `EmbeddedSurfaceGenerator`), drops XML
   fragments that are only `<Included>` by other decks, and resolves every
   `file=` attribute so decks with missing payloads are separated.
2. **`run_decks.py`** — copies `GEOS/inputFiles` to a throwaway tree and runs
   each selected deck in a fresh container with the built binary. Statuses:
   `pass | fail | timeout | xml-error | missing-file`.
3. **`summarize.py`** — writes `RESULTS.md` (totals, per-category table, real
   GEOS error excerpt for every non-pass).
4. **`requirements.py`** — maps each deck to the five Task-1 capabilities and
   writes `REQUIREMENTS.md`.
5. **`derive_velocity.py`** — reconstructs a Darcy velocity field from a solved
   matrix `.vtu` (`v = -(k/μ) ∇p`), used to show the solution is physically
   live, not just written.

## Requirements flags (`REQUIREMENTS.md`)

| Flag | Capability |
|---|---|
| A | external mesh imported (`VTKMesh`) |
| B | explicit fracture region (`SurfaceElementRegion` present) |
| C | conformal face elements (`subRegionType="faceElement"`, the default) |
| D | embedded elements (EDFM/EFEM) |
| E | rock-matrix region (`CellElementRegion`) |
| F | fracture–matrix coupling (surface + cell region + a solver targeting both) |

## Result (GEOS 1.1.0, sha1 `ef14524e1b`)

90 relevant decks selected, **78 runnable** (12 need data the repository does not
ship, e.g. `MESH/` or `GEOSDATA/`):

* **62 pass, 13 fail, 3 timeout**
* A 45/33 · B 27/27 · C 18/18 · D 22/17 · E 33/31 · F 27/27
  (decks with the flag / of those, how many pass)
* **A+C+E+F together: 7 decks, all 7 pass** — the five
  `poromechanicsFractures/Contact/AugmentedLagrangianMultipliers/ALM_inclinedFault_*`
  cases, `singlePhaseFlowFractures/fractureFlow_conforming_2d_vtk_input.xml`
  and `surfaceGeneration/cube_8.xml`.

Every non-pass has a cause that is *not* a GEOS mesh-representation limitation:

* 5 — shipped lagrangian decks are stale (`totalDisplacement`, `traction`);
* 3 — empty / Git-LFS-pointer payloads (`dome_smoke.vti` is a 128-byte pointer);
* 5 — sample field/set targeting errors (empty sets, unreferenced regions,
  `long long` node set);
* 3 — heavy benchmarks exceeding even a 900 s budget (all > 15 min).

One sample needed a data fix rather than a harness fix: GEOS' own
`singlePhaseFlowFractures/fracture.vtu` still ships the legacy
`duplicated_nodes` array and no `GlobalIds`. Renaming it to `collocated_nodes`
and adding 0-based `IdType="1"` global ids (exactly what `conversion/` emits)
makes the deck run to completion — the repaired copy lives in
`geos-tests/fixtures/singlePhaseFlowFractures/` and is what `62 pass` counts.

## Re-running

Prerequisites: the GEOS binary at `geos-build/bin/geosx` and the TPL image
`geosx/ubuntu24.04-gcc13:364-1112`.

```bash
python3 validation/select_geos_decks.py
python3 validation/run_decks.py --jobs 4 --timeout 240
python3 validation/summarize.py
python3 validation/requirements.py
```

`--only <substr>` and `--limit` are available for spot checks.
