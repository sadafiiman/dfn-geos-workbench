# User Guide — working with the dfn–GEOS Workbench panel

> **On Windows?** Read the 5-page
> [`TUTORIAL_windows.pdf`](TUTORIAL_windows.pdf) first — it is the short
> copy-and-run walkthrough. This guide is the full reference: every screen,
> every stage, and what to do with the files you get.

The panel is a small web app that manages **cases** for the
dfnWorks → GEOS integration. Each case owns its input parameters, input
files, output files and job history, and offers a three-stage pipeline:

```
   ┌──────────────────────┐   ┌──────────────────────┐   ┌─────────────────┐
   │ 1 · dfnWorks mesh    │ → │ 2 · Convert → GEOS   │ → │ 3 · Run GEOS    │
   │ dfnGen → LaGriT →    │   │ UCD → VTK multi-block│   │ coupled flow in │
   │ full_mesh(.uge) +    │   │ main.vtu + fracture  │   │ matrix + frac-  │
   │ DFM mesh + facets    │   │ .vtu + XML decks     │   │ tures → *.pvd   │
   └──────────────────────┘   └──────────────────────┘   └─────────────────┘
```

* **Stage 1** runs dfnWorks — natively, or inside the official
  `ees16/dfnworks` docker image (recommended, especially on Windows).
* **Stage 2** always runs locally; it needs only Python + numpy.
* **Stage 3** runs the deck with a compiled GEOS binary *or* a GEOS docker
  image (see §3). It is optional: stages 1–2 already produce the complete
  model.

---

## 0. The simplest way — *Quick process* (upload → results)

If you just want to feed files in and get results out, skip the manual steps
below and use **Quick process** in the top bar:

1. **Pack your files.** Zip up whatever you have — e.g. a dfnWorks output
   folder (`full_mesh.inp`, `params.txt`, `polys/`, and optionally
   `dfm_mesh/`), your own driver/inputs, or a GEOS XML + mesh. A zip whose
   contents sit inside one top-level folder is fine (the folder is stripped).
   Loose files (no zip) also work: dfnWorks-like files are placed in
   `output/` automatically.
2. **Open Quick process** → optionally give a name → choose
   *Auto-detect* (default) → **Process**.
3. The panel inspects the upload and **runs the right stage(s) by itself**:

   | Found in the upload | Pipeline run |
   |---|---|
   | `full_mesh.inp` / `params.txt` / `polys/` / `dfm_mesh/…` | **convert** → GEOS case + XML deck(s) |
   | `dfn_driver.py` / `input_generator.dat` / `case_params.json` | **dfnWorks mesh → convert** (→ GEOS if configured) |
   | `*.xml` + `*.vtm`/`*.vtu`/`*.vtp` | **run GEOS** |
   | nothing recognised | full pipeline |

   Stages run **chained**: when one finishes successfully the next starts
   automatically. The case page auto-refreshes while jobs are running.
4. **Download the result** with the **⬇ Download results (.zip)** button on
   the case page. The archive contains your uploaded inputs *and* the
   generated `geos_case/` (`case.vtm`, `main.vtu`, `fracture.vtu`,
   `geos_dfn_fractures.xml`) plus the EDFM deck
   (`geos_case_edfm/geos_dfn_edfm.xml`, the runnable one), plus the GEOS
   results (`*.pvd` + per-step `*.vtu`) when stage 3 ran.

That's the whole loop: **ZIP in → ZIP out**. Everything below is the manual
route when you want to control parameters or inspect each stage.

---

## 1. The panel, screen by screen

The top bar is always visible:

| Item | What it is |
|---|---|
| **dfn–GEOS Workbench** | the title; clicking it returns to the Dashboard |
| **Quick process** | the one-page upload → run → download screen (§0) |
| **＋ New case** | the manual case-creation form (§4) |
| **Settings** | paths, backends and docker images — set once (§3) |
| **Docs** | renders this guide inside the browser |

### 1.1 Dashboard

Lists every case with its name, description, creation time and the status of
its last job. Under the title it prints the **three resolved paths**
(dfnWorks repository, GEOS executable, python) so you can see immediately
whether configuration was picked up. Buttons per case: **open**, **download
results (.zip)**, **delete**.

### 1.2 Quick process page

One form: *name* (optional), a file/zip drop area, an *action* selector
(*Auto-detect* is the default; *Convert only*, *Generate + convert*,
*Run GEOS* force a specific path) and a **Process** button. Submitting
creates the case, extracts the upload and starts the chained jobs. You land
directly on the new case page.

### 1.3 New case page

The manual form: name, description, domain size, mesh size `h`, seed,
threads, the DFM checkbox and the two optional JSON inputs. See §4 for each
field. **Create** makes `cases/<name>/` and opens the case page.

### 1.4 Case page

The working screen, five areas top to bottom:

| Area | Contents |
|---|---|
| **Header** | case name/description and the **⬇ Download results (.zip)** button |
| **Pipeline** | the three stage buttons — `1 · dfnWorks mesh`, `2 · Convert → GEOS`, `3 · Run GEOS` |
| **Jobs** | one row per run: stage, status (queued/running/done/failed), duration, return code, **log** link, **cancel** |
| **Upload input files** | send files into the case; the *Sub-directory* field places them (e.g. `output/dfm_mesh`, `geos_case`) |
| **Artifacts** | the notable outputs each successful job registered automatically (click to preview/download) |
| **Files** | the complete case tree — `output/`, `dfm_mesh/`, `geos_case/`, `geos_case_edfm/`, `dfn_edfm/`, `logs/`, uploads — with preview / `raw` download / `del` |

Buttons are independent: you may run stage 2 on a mesh produced earlier, or
re-run only stage 3 after changing a deck. Jobs never block the page.

### 1.5 Settings page

One form for every path and backend (§3), plus the *Prepend compat/vendor*
checkbox. **Save** writes `config.json` next to the panel and returns you to
the Dashboard.

### 1.6 Log page

Full stdout+stderr of one job, auto-refreshing while it runs. This is the
first place to look when a stage fails — the panel also stores the tail of
the log in the job row.

---

## 2. Start the panel

```bash
cd dfn-geos-workbench
python run_panel.py                 # default port 8765
# or: python run_panel.py --port 9000 --home /path/to/panel_data
```

The banner tells you exactly where it listens:

```
dfn-GEOS Workbench panel → http://localhost:8765
```

Open that address. Keep the terminal running; `Ctrl+C` stops the panel.

If the port is already used the panel **stops with a clear message** instead
of half-starting:

```
cannot listen on port 8765: [Errno 98] Address already in use
another program is already using it — try:
    python run_panel.py --port 8766
```

Runtime data (SQLite database, cases, logs) lives next to the code in
`panel.db` and `cases/` unless `--home` says otherwise.

## 3. Configure it once (Settings page)

Click **Settings** in the top bar and fill in:

| Field | What to put | Example |
|---|---|---|
| dfnWorks repository | path to your dfnWorks clone | `/home/you/dfnWorks` |
| LaGriT executable | a working `lagrit` binary (empty → docker is used) | *(empty)* |
| GEOS executable | path to a compiled `geosx` binary (**leave empty** with the docker backend) | *(empty)* |
| Python for dfnWorks | leave blank to use the panel's Python | *(blank)* |
| dfnWorks backend | `auto`, `native` or `docker` | `docker` |
| dfnWorks docker image | image used for the docker backend | `ees16/dfnworks:latest` |
| GEOS backend | `auto`, `native` or `docker` | `docker` |
| GEOS docker image | image containing `geosx` | `dfn-geos:1.1` |
| *Prepend compat/vendor* | keep checked unless your Python has the full pydfnworks dependencies | ✓ |

Click **Save**. The dashboard then shows the resolved paths.

**How `auto` decides.** `auto` uses a configured binary if one is set,
otherwise a configured docker image, otherwise native. So with the docker
backend you never need a GEOS executable on the host — the panel runs
`/opt/geos/bin/geosx` inside the image.

> **Tip (recommended on any OS):** `docker pull ees16/dfnworks:latest` and set
> *dfnWorks backend* = `docker`. Stage 1 then needs no native LaGriT build
> (released LaGriT binaries do not support current dfnWorks).

## 4. Create a case

Dashboard → **＋ New case**. Fill in:

* **Name** — letters/digits/`-`/`_` only; becomes the folder name under `cases/`.
* **Description** — free text.
* **Domain X/Y/Z (m)** — the box size; it is centred on the origin, so
  `6 × 6 × 6` means x,y,z ∈ [−3, 3].
* **Mesh h (m)** — target triangle edge length. Smaller = finer mesh and
  slower. Start around `0.3 – 0.4` for a 6 m domain.
* **Seed** — fixes the random fracture network (reproducibility).
* **Threads** — LaGriT/dfnGen parallelism (`4` is fine on a laptop).
* **Also build conforming fracture–matrix DFM mesh** — keep checked if you
  want the *conformal* GEOS path (the converter needs it). Uncheck to only
  produce the DFN surface mesh.
* **Stochastic families (JSON, optional)** — leave empty for the default
  network (two orthogonal constant-size families, 24 fractures).
* **User fractures (JSON, optional)** — explicit rectangular fractures.

Create → you land on the case page.

### Input JSON formats

*Stochastic families* (list of objects):

```json
[
  {"distribution": "constant", "constant": 2.0, "probability": 1.0,
   "trend": 0.0, "plunge": 0.0, "aspect": 1.0, "kappa": 20.0},
  {"distribution": "constant", "constant": 2.0, "probability": 1.0,
   "trend": 35.0, "plunge": 90.0, "aspect": 1.0, "kappa": 20.0}
]
```

*User fractures* (list of objects):

```json
[
  {"radii": 2.0, "translation": [-1.6, 0, 0], "normal": [0, 0, 1]},
  {"radii": 2.0, "translation": [ 1.6, 0, 0], "normal": [0, 0, 1]}
]
```

⚠️ dfnGen/FRAM rules: an intersection **shorter than `h`** is rejected, and
so are fractures whose edges run **closer than `h`** to another fracture's
edge. Keep overlaps well above `h` — if a run ends with *"no intersecting
fractures"*, enlarge the fractures or reduce `h`.

## 5. Run the pipeline — what each stage does

On the case page, click the three buttons in order. Each click creates a
**job** that runs in the background — the page never blocks.

### Stage 1 · dfnWorks mesh

| | |
|---|---|
| **Does** | generates the stochastic DFN (dfnGen/FRAM), meshes it with LaGriT, then builds the conforming DFM tetrahedral mesh |
| **Consumes** | the case parameters (domain, `h`, seed, threads, families/user fractures) |
| **Produces** | `output/full_mesh.inp` + `.uge` + `.stor`, `params.txt`, `poly_info.dat`, `materialid.dat`, `polys/`, and `output/dfm_mesh/dfm_tet_mesh.inp` + `facets_merged.inp` |
| **Time** | seconds (tiny networks) to minutes |
| **Verify** | job row turns **done**; the log ends with the node/element counts; the Artifacts table lists `full_mesh.inp` |
| **Typical failures** | *"no intersecting fractures"* (FRAM rules above), `MO DOES NOT EXIST: mo_poisson_pts` (released LaGriT → use docker), *"Missing percent of mesh is larger than tolerance"* (slivers; refine `h`) |

### Stage 2 · Convert → GEOS

| | |
|---|---|
| **Does** | translates the dfnWorks meshes into GEOS' VTK input: one multi-block file plus two XML decks |
| **Consumes** | `output/dfm_mesh/` (conforming) and `output/` (fracture polygons, for EDFM) |
| **Produces** | `geos_case/case.vtm`, `geos_case/main.vtu` (rock matrix, tetrahedra, region attribute + GlobalIds), `geos_case/fracture.vtu` (explicit fracture surfaces: triangles, `collocated_nodes`, `fracture_id`, `aperture`), `geos_case/geos_dfn_fractures.xml` (conformal deck) **and** `geos_case_edfm/geos_dfn_edfm.xml` (EDFM deck) |
| **Time** | seconds |
| **Verify** | log prints `matrix nodes / cells`, `fractures`, `fracture triangles`; the Artifacts table lists both decks |
| **Notes** | `fracture.vtu` keeps every fracture element that survived the DFM meshing (slivers at intersection lines can be dropped — the log reports the percentage) |

### Stage 3 · Run GEOS

| | |
|---|---|
| **Does** | runs a coupled single-phase flow simulation with the fracture network embedded in the rock matrix |
| **Consumes** | the decks from stage 2, plus the GEOS backend configured in Settings |
| **Produces** | a time series — `<name>.pvd` + `<name>/0000N0/matrix/Level0/{RockMatrix,Fracture}/rank_0.vtu` — with `pressure` and derived fields |
| **Time** | ~10 s for a small network; minutes for dense ones |
| **Verify** | job row **done**, return code 0; the Artifacts table lists the `.pvd` and several `.vtu`; each log line shows `Linear Solver | Success | Iterations: n` |
| **Deck choice** | the panel prefers `geos_case_edfm/geos_dfn_edfm.xml` (proven end-to-end), then the conformal deck, then any runnable `*.xml` in the case |
| **If it fails** | *"GEOS executable is not configured"* → set the GEOS backend (§3). The model artifacts from stage 2 are complete and unaffected |

### Watching a job

Click **log** in the Jobs table (or the job number) to open the live log page;
it refreshes automatically while the job runs and reloads when it finishes.
**Cancel** stops a running job. Failed jobs keep their full log for diagnosis.

## 6. Files: upload, browse, preview, download

The case page has three file areas:

* **Upload input files** — send files *into* the case (e.g. your own
  `pflotran.in`, a custom GEOS XML, or a pre-computed `full_mesh.inp`). Use the
  *Sub-directory* field to place them, e.g. `geos_case` or `uploads`.
* **Artifacts** — the notable outputs registered automatically by each job
  (stage 1 lists the dfnWorks meshes, stage 2 the decks and VTK files,
  stage 3 the `.pvd`/`.vtu` results).
* **Files** — the complete case directory tree (`output/`, `geos_case/`,
  `logs/`, uploads…). Click a file to preview it (text formats) or `raw` to
  download it. `del` removes it.

Everything lives under `cases/<case-name>/` on disk, so you can also work
with it from the shell or an editor.

## 7. Typical end-to-end sessions

**A. Study a network and produce a GEOS case (no GEOS binary needed)**

```
Settings (once) → New case (6×6×6, h=0.35, DFM ✓)
→ "1 · dfnWorks mesh"   → wait for done
→ "2 · Convert → GEOS"  → wait for done
→ open Files ▸ geos_case ▸ geos_dfn_fractures.xml to preview the deck
→ download case.vtm / main.vtu / fracture.vtu for inspection (§10)
```

**B. Full simulation** — same, then (after configuring the GEOS backend)

```
→ "3 · Run GEOS" → wait for done → open dfn_edfm.pvd in ParaView (§10)
```

**C. Bring your own mesh** — create a case, upload a
`dfm_tet_mesh.inp` + `facets_merged.inp` into `output/dfm_mesh/` (using the
Sub-directory field), then run stage 2 only.

**D. Bring your own GEOS sample** — upload a folder of GEOS XML (e.g. a copy
of `GEOS/inputFiles/<category>/`) through **Quick process**; the panel
detects `*.xml` and runs stage 3 on the runnable deck. Decks that only
`<Included>` other files are skipped automatically.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser shows **gibberish / binary** instead of the panel | You are on a port owned by another program — start with `--port 9000` and open that |
| Opening a `.pvd` / `.vtu` shows **only XML text** | That is correct — those files are data, not pictures. Open them in **ParaView** (see §10.2); the panel now says so on the preview page |
| `cannot listen on port N` at startup | Port already used; the message prints the next port to try |
| `'python' not found` (Ubuntu) | Use `python3` (or `apt install python-is-python3`) |
| *"no intersecting fractures"* in the log | FRAM rejected all intersections: enlarge fractures / raise overlap, lower `h`, or use the default families |
| Stage 1 fails with `MO DOES NOT EXIST: mo_poisson_pts` | You are using a released LaGriT binary; use the docker backend or a LaGriT built from source (see `docs/INSTALL_ubuntu.md`) |
| Stage 1 fails with `Missing percent of mesh is larger than tolerance` | The conforming DFM mesh lost sliver triangles; the panel already passes `allowed_percentage=5` — for very dense networks refine `h` |
| Stage 3 fails: *"GEOS executable is not configured"* | Set *GEOS backend* = `docker` + *GEOS docker image*, or point *GEOS executable* at a binary |
| GEOS deck fails with *"this FieldSpecification targets (an) empty set(s)"* | A source/sink box in your own deck captures no cells; align it with the mesh cell centres |
| Output files owned by `root` after a docker job | Should not happen (the panel runs GEOS as your user and restores ownership); if it does, `docker run --rm --entrypoint chown -v "$PWD":/w ees16/dfnworks:latest -R $(id -u):$(id -g) /w` |
| `docker: permission denied` | Add your user to the `docker` group and re-login, or run the panel with sufficient rights |
| Files missing after cloning the repo | Heavy artifacts are git-ignored; regenerate with the `poc/` scripts (see README) |

## 9. Command-line equivalents

Everything the panel does has a script equivalent:

```bash
# stage 1 (docker backend)
docker run --rm -v "$PWD":/app -w /app ees16/dfnworks:latest python3 /app/poc/run_dfn_example.py
docker run --rm -v "$PWD":/app -w /app ees16/dfnworks:latest python3 /app/poc/run_dfm.py

# stage 2
python conversion/dfn_to_geos.py --dfm-dir poc/output/dfm_mesh --out poc/geos_case
python conversion/poly_to_geos_edfm.py --job-dir poc/output --out poc/geos_case_edfm

# stage 3 (EDFM deck, GEOS in a container)
docker run --rm -v "$PWD":/app -w /app --user "$(id -u):$(id -g)" -e HOME=/tmp \
    dfn-geos:1.1 /opt/geos/bin/geosx -i /app/geos_case_edfm/geos_dfn_edfm.xml

# layer-0 tests
python tests/test_converters.py
```

## 10. Using the outputs

After stage 3 the case directory contains a **time series**. Here is what to
open, and why.

### 10.1 The files, in the order you will want them

| File (relative to `cases/<case>/`) | What it is | Open with |
|---|---|---|
| `dfn_edfm.pvd` | **the simulation** — index of every time step, matrix + fractures | **ParaView** (this is the one) |
| `dfn_edfm/0000N0/matrix/Level0/RockMatrix/rank_0.vtu` | rock matrix at one step (pressure, mass, permeability…) | ParaView (single step) |
| `dfn_edfm/0000N0/matrix/Level0/Fracture/rank_0.vtu` | fracture network at one step (pressure, aperture, area) | ParaView |
| `geos_case/case.vtm` | the **conforming** model: rock block + explicit fracture surfaces | ParaView (geometry) |
| `geos_case/fracture.vtu` | fractures alone (`fracture_id`, `aperture`, `collocated_nodes`) | ParaView |
| `geos_case/main.vtu` | rock matrix alone (tetrahedra) | ParaView |
| `geos_case_edfm/geos_dfn_edfm.xml`, `geos_case/geos_dfn_fractures.xml` | the GEOS input decks | text editor / GEOS |
| `validation/velocity/velocity.vtu` | Darcy velocity derived from the solution | ParaView |

> **Open the `.pvd`, not the `.vtu`.** A single `rank_0.vtu` is one time step
> of one region; the `.pvd` loads the whole series with the time slider.

### 10.2 ParaView recipe

1. **File → Open** → `dfn_edfm.pvd` → **Apply**.
   The pipeline tree shows both regions:
   `matrix/Level0/RockMatrix` and `matrix/Level0/Fracture`.
2. **Animate** with the ▶ button / time slider (steps `000000 … 000050`,
   i.e. t = 0 … 50 000 s).
3. **Colour by pressure** — select a region, then choose **`pressure`** in the
   colouring dropdown. Use the *Rescale to data range over all time steps*
   button to keep colours comparable while animating.
4. **Show the fractures** — select `Fracture`, Apply, colour by `pressure` or
   `elementAperture`. They are 2-D elements embedded in the rock; switch to
   **Surface With Edges** (or increase point size) to make them visible.
5. **Empty colour dropdown?** GEOS writes cell data — toggle the
   Point/Cell-array button next to the array selector.
6. **Velocity** — open `validation/velocity/velocity.vtu` (or the copy in the
   downloaded zip) and colour by `velocityMagnitude`, or add a **Glyph**
   filter on `velocity` to draw arrows.

### 10.3 Beyond ParaView

* The `.vtu` files are plain XML+ASCII — the numbers can be read with Python
  (`numpy`), or in VisIt, or converted with `meshio` to `.vtk`/`.xdmf`.
* `validation/velocity/velocity.csv` is the tabular form of the velocity
  field (element index, centre, velocity components, magnitude) — convenient
  for spreadsheets and plots.
* The decks are ordinary GEOS XML: copy one, change pressures/aperture/
  permeability, and re-run stage 3 on the same mesh without re-meshing.
