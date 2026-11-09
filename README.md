# dfn–GEOS Workbench

A management panel and integration toolkit for the two open-source projects
**[dfnWorks](https://github.com/lanl/dfnWorks)** (3-D discrete fracture network
generator) and **[GEOS](https://geosx-geosx.readthedocs-hosted.com/en/latest/)**
(subsurface coupled simulator).

It delivers **Task 1 — Technical Feasibility Assessment: dfnWorks–GEOS Mesh
Compatibility** as a complete, runnable package:

* a working **web panel** to create cases, upload/manage inputs and outputs,
  and drive the whole pipeline (`dfnWorks mesh → convert → GEOS`) with live
  logs — cross-platform: Ubuntu *and* Windows, standard library only;
* a **mesh converter** (`dfnWorks AVS/UCD → GEOS VTK multi-block`) that
  preserves fracture surfaces, connectivity and fracture–matrix incidence;
* a **proof of concept** generated from a real dfnWorks run, verified against
  the VTK library with the same lookup pattern GEOS uses;
* the **technical report** answering all five deliverable questions
  (`report/feasibility_report.md`).

```
dfn-geos-workbench/
├── report/feasibility_report.md   ← Task-1 deliverable (start here)
├── conversion/                    ← dfnWorks → GEOS converters
│   ├── dfn_to_geos.py             ← conformal path (DFM mesh → VTM + XML)
│   ├── poly_to_geos_edfm.py       ← EDFM path (fracture outlines → XML)
│   ├── avs_ucd.py                 ← AVS/UCD reader (LaGriT flavour)
│   └── vtk_xml.py                 ← VTK XML writers (vtu/vtp/vtm)
├── poc/                           ← proof of concept
│   ├── run_dfn_example.py         ← dfnGen + LaGriT meshing (docker or native)
│   ├── run_dfm.py                 ← conforming fracture–matrix (DFM) mesh
│   ├── output/                    ← the real dfnWorks run produced here
│   ├── geos_case/                 ← converted GEOS case (VTM + XML)
│   └── geos_case_edfm/            ← EDFM variant (InternalMesh + Rectangles)
├── panel/                         ← the management panel (stdlib web app)
│   ├── webapp.py                  ← HTTP server + UI + APIs
│   ├── jobs.py / pipeline.py      ← job runner & pipeline stages
│   ├── config.py / db.py          ← settings + sqlite storage
│   └── static/                    ← css/js
├── compat/, vendor/               ← lightweight shims (pandas/pyvtk/h5py/fpdf/
│                                    seaborn/mplstereonet) + vendored networkx
│                                    so pydfnworks runs with numpy only
├── tools/                         ← LaGriT binaries used during the study
├── run_panel.py                   ← panel entry point
├── setup_windows.ps1 / .cmd       ← one-command Windows setup (clone/pull/config/start)
├── start_windows.cmd              ← daily Windows launcher
└── docs/
    ├── TUTORIAL_windows.pdf      ← illustrated input→output walkthrough
    ├── INSTALL_ubuntu.md          ← development platform
    └── INSTALL_windows.md         ← deployment platform
```

## Quick start

```bash
# 1) panel (no dependencies beyond Python + numpy)
#    Windows, complete from zero (installs everything, starts the panel):
#      git clone https://github.com/sadafiiman/dfn-geos-workbench.git C:\dfn-project\dfn-geos-workbench
#      cd C:\dfn-project\dfn-geos-workbench
#      setup_windows.cmd
#      (add -WithGeos to also build the GEOS solver image; start_windows.cmd next time)
#    then (every platform):
python3 run_panel.py --port 8765        # open http://localhost:8765

# Simplest workflow - ZIP in, ZIP out:
#   open the panel -> "Quick process" -> drop a zip of your dfnWorks files
#   (or existing outputs) -> Process -> "Download results (.zip)".
#   The panel auto-detects what to run (see docs/USER_GUIDE.md).

# 2) proof of concept (CLI variant)
cd poc
docker run --rm -v "$(pwd)/..":/app -w /app ees16/dfnworks:latest \
    python3 /app/poc/run_dfn_example.py                 # DFN mesh
docker run --rm -v "$(pwd)/..":/app -w /app ees16/dfnworks:latest \
    python3 /app/poc/run_dfm.py                         # conforming DFM mesh
cd ../conversion
python3 dfn_to_geos.py --dfm-dir ../poc/output/dfm_mesh --out ../poc/geos_case
python3 poly_to_geos_edfm.py --job-dir ../poc/output --out ../poc/geos_case_edfm

# 3) run GEOS (wherever a geos binary is available)
geosx -i ../poc/geos_case_edfm/geos_dfn_edfm.xml   # EDFM deck (runs today)
```

The panel drives the same three stages with one click; stage 1 runs natively
or inside the official `ees16/dfnworks` docker image (recommended), stage 2
always runs locally (numpy only), stage 3 needs a GEOS executable (configure
in *Settings*).

## Key results of the feasibility study

| Question | Answer |
|---|---|
| Direct import of dfnWorks meshes into GEOS | **No** — GEOS reads VTK only; dfnWorks writes AVS/UCD, UGE, LaGriT binary, Exodus |
| Explicit fracture representation in GEOS | **Yes** — conformal `SurfaceElementRegion` (face elements from a `.vtm` face block) or EDFM/EFEM embedded elements |
| Required conversion | UCD → VTK multi-block with `GlobalIds` + `collocated_nodes` + `attribute` regions + `aperture` field — implemented and verified |
| Recommended approach | **Option B** (conversion): EDFM executed and converged; conformal path generated, needs a split matrix |
| Validation against GEOS samples | **78 runnable decks from `GEOS/inputFiles`: 62 pass**; every explicit-fracture (27/27), conformal (18/18) and fracture–matrix coupling (27/27) deck passes |

See `report/feasibility_report.md` for the full assessment, including the
LaGriT deployment caveats discovered during the study.
