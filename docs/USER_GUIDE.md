# User Guide — working with the dfn–GEOS Workbench panel

> **On Windows?** Read the 3-page
> [`TUTORIAL_windows.pdf`](TUTORIAL_windows.pdf) first — it is the short
> input→output walkthrough. This guide is the full reference.

The panel is a small web app that manages **cases** for the
dfnWorks → GEOS integration. Each case owns its input parameters, input
files, output files and job history, and offers a three-stage pipeline:

```
   ┌──────────────────────┐   ┌──────────────────────┐   ┌─────────────────┐
   │ 1 · dfnWorks mesh    │ → │ 2 · Convert → GEOS   │ → │ 3 · Run GEOS    │
   │ dfnGen → LaGriT →    │   │ UCD → VTK multi-block│   │ single-phase    │
   │ full_mesh(.uge) +    │   │ main.vtu + fracture  │   │ fracture flow   │
   │ DFM mesh + facets    │   │ .vtu + XML decks     │   │ (needs a GEOS   │
   └──────────────────────┘   └──────────────────────┘   │  executable)    │
                                                          └─────────────────┘
```

* Stage 1 runs dfnWorks (natively, or inside the official `ees16/dfnworks`
  docker image — recommended, especially on Windows).
* Stage 2 always runs locally; it needs only Python + numpy.
* Stage 3 needs a compiled GEOS binary configured in **Settings**; until then
  it stops with a clear message and you can still use the generated deck.

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

## 1. Start the panel

```bash
cd dfn-geos-workbench
python run_panel.py                 # default port 8765
# or: python run_panel.py --port 9000 --home /path/to/panel_data
```

Open **http://localhost:8765** in a browser. Keep the terminal running; press
`Ctrl+C` there to stop the panel. (Runtime data — SQLite database, cases,
logs — is stored next to the code in `panel.db` and `cases/`.)

## 2. Configure it once (Settings page)

Click **Settings** in the top bar and fill in:

| Field | What to put | Example (Ubuntu) |
|---|---|---|
| dfnWorks repository | path to your dfnWorks clone | `/home/you/dfnWorks` |
| LaGriT executable | path to a working `lagrit` binary (empty → docker is used) | `/home/you/dfn-geos-workbench/tools/lagrit` |
| GEOS executable | path to a compiled `geos` binary (optional) | `/home/you/GEOS/build/geos` |
| Python for dfnWorks | leave blank to use the panel's Python | *(blank)* |
| dfnWorks backend | `auto` (native if possible, else docker), `native`, `docker` | `auto` |
| dfnWorks docker image | image used for the docker backend | `ees16/dfnworks:latest` |
| GEOS backend / image | `native`, or `docker` + a GEOS image | `native` |
| *Prepend compat/vendor* | keep checked unless your Python env has the full pydfnworks dependencies | ✓ |

Click **Save**. The dashboard shows the three resolved paths at the top, so
you can immediately see whether detection succeeded.

> **Tip (recommended on any OS):** install Docker and run
> `docker pull ees16/dfnworks:latest`. Then set *dfnWorks backend* to
> `docker` (or `auto`) and stage 1 works without any native LaGriT build —
> the released LaGriT binaries do not support current dfnWorks.

## 3. Create a case

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

## 4. Run the pipeline

On the case page, click the three buttons in order. Each click creates a
**job** that runs in the background — the page never blocks.

1. **1 · dfnWorks mesh** — expected time: seconds (tiny networks) to minutes.
   Success registers artifacts: `full_mesh.inp`, `full_mesh.uge`,
   `full_mesh_vol_area.uge`, `materialid.dat`, `params.txt`,
   `poly_info.dat` and the DFM mesh (`dfm_mesh/dfm_tet_mesh.inp` + facets).
2. **2 · Convert → GEOS** — produces `geos_case/`:
   * `case.vtm` — the multi-block container GEOS reads,
   * `main.vtu` — rock matrix (tetrahedra, region attribute, GlobalIds),
   * `fracture.vtu` — explicit fracture surface (triangles, `collocated_nodes`,
     `fracture_id`, `aperture`),
   * `geos_dfn_fractures.xml` — the *conformal* deck.
   And whenever the DFN job directory is present, the EDFM reconstruction
   `geos_case_edfm/geos_dfn_edfm.xml` as well.
3. **3 · Run GEOS** — runs the deck with the configured executable and
   registers the results. It prefers the **EDFM deck** (proven end-to-end),
   because the conformal deck needs a fracture-split matrix (report §6.3).
   Without a configured GEOS binary the job fails fast with *"GEOS executable
   is not configured"* — this is expected and harmless; every model artifact
   is already produced by stage 2.

### Watching a job

Click **log** in the Jobs table (or the job number) to open the live log page;
it refreshes automatically while the job runs and reloads when it finishes.
**Cancel** stops a running job. Failed jobs keep their full log for diagnosis.

## 5. Files: upload, browse, preview, download

The case page has three file areas:

* **Upload input files** — send files *into* the case (e.g. your own
  `pflotran.in`, a custom GEOS XML, or a pre-computed `full_mesh.inp`). Use the
  *Sub-directory* field to place them, e.g. `geos_case` or `uploads`.
* **Artifacts** — the notable outputs registered automatically by each job.
* **Files** — the complete case directory tree (`output/`, `geos_case/`,
  `logs/`, uploads…). Click a file to preview it (text formats) or `raw` to
  download it. `del` removes it.

Everything lives under `cases/<case-name>/` on disk, so you can also work
with it from the shell or an editor.

## 6. Typical end-to-end sessions

**A. Study a network and produce a GEOS case (no GEOS binary needed)**

```
Settings (once) → New case (6×6×6, h=0.35, DFM ✓)
→ "1 · dfnWorks mesh"   → wait for done
→ "2 · Convert → GEOS"  → wait for done
→ open Files ▸ geos_case ▸ geos_dfn_fractures.xml to preview the deck
→ download case.vtm / main.vtu / fracture.vtu for inspection
```

**B. Full simulation** — same, then (after configuring `geos_exe`)

```
→ "3 · Run GEOS" → open the log → find the produced VTK/VTU files under Outputs
```

**C. Bring your own mesh** — create a case, upload a
`dfm_tet_mesh.inp` + `facets_merged.inp` into `output/dfm_mesh/` (using the
Sub-directory field), then run stage 2 only.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| *"no intersecting fractures"* in the log | FRAM rejected all intersections: enlarge fractures / raise overlap, lower `h`, or use the default families |
| Stage 1 fails with `MO DOES NOT EXIST: mo_poisson_pts` | You are using a released LaGriT binary; use the docker backend or a LaGriT built from source (see `docs/INSTALL_ubuntu.md`) |
| Stage 1 fails with `Missing percent of mesh is larger than tolerance` | The conforming DFM mesh lost sliver triangles; the panel already passes `allowed_percentage=5` — for very dense networks refine `h` |
| Stage 3 fails: *"GEOS executable is not configured"* | Set `geos_exe` in Settings (build GEOS, or use WSL2/Docker on Windows) |
| Output files owned by `root` after a docker job | Should not happen (the panel restores ownership); if it does, run `docker run --rm -v "$PWD":/w ees16/dfnworks:latest chown -R $(id -u):$(id -g) /w` |
| `docker: permission denied` | Add your user to the `docker` group and re-login, or run the panel with sufficient rights |
| Files missing after cloning the repo | Heavy artifacts are git-ignored; regenerate with the `poc/` scripts (see README) |

## 8. Command-line equivalents

Everything the panel does has a script equivalent:

```bash
# stage 1 (docker backend)
docker run --rm -v "$PWD":/app -w /app ees16/dfnworks:latest python3 /app/poc/run_dfn_example.py
docker run --rm -v "$PWD":/app -w /app ees16/dfnworks:latest python3 /app/poc/run_dfm.py

# stage 2
python conversion/dfn_to_geos.py --dfm-dir poc/output/dfm_mesh --out poc/geos_case
python conversion/poly_to_geos_edfm.py --job-dir poc/output --out poc/geos_case_edfm

# stage 3
geos -i poc/geos_case/geos_dfn_fractures.xml

# layer-0 tests
python tests/test_converters.py
```
