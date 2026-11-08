# dfnWorks → GEOS Workbench
## Windows quick tutorial — input in, results out

The workbench turns a dfnWorks fracture network into a **GEOS-ready model**:
a VTK mesh with an explicit fracture block, and the XML input deck(s) that run
it. You feed it files through a small web panel and download the results.

---

## 1. Install once

1. **Python 3.10+** — <https://python.org> (tick *Add python.exe to PATH*).
2. **Docker Desktop** — <https://docker.com/products/docker-desktop>, keep the
   **WSL2 backend** enabled.
3. Open *PowerShell* and install the Python dependency, then the dfnWorks image:

```bat
pip install numpy
docker pull ees16/dfnworks:latest
```

> Docker must be running (whale icon in the tray) before you start a job.

---

## 2. Start the panel

```bat
cd C:\path\to\dfn-geos-workbench
python run_panel.py
```

Open **http://localhost:8765**. Keep PowerShell open; `Ctrl+C` stops the panel.
Cases, logs and the database are written next to the code (`cases\`, `panel.db`).

---

## 3. Configure it once

Click **Settings** and fill in:

| Field | Value on Windows |
|---|---|
| dfnWorks backend | `docker` |
| dfnWorks docker image | `ees16/dfnworks:latest` |
| dfnWorks repository | `C:\path\to\dfnWorks` (only needed for native runs) |
| GEOS executable | leave empty (see step 6) |

**Save**. The dashboard now shows the resolved paths.

---

## 4. Give it your input

Click **Quick process** in the top bar and either

* **drop a ZIP** on the page, or
* **pick loose files** (they are packed automatically).

Accepted content — the panel detects it and runs the right stage by itself:

| Your files | What it does |
|---|---|
| `full_mesh.inp`, `params.txt`, `polys\`, `dfm_mesh\` | converts to a GEOS case |
| `dfn_driver.py`, `input_generator.dat`, `case_params.json` | generates the dfnWorks mesh, then converts |
| `*.xml` + `*.vtm` / `*.vtu` | runs GEOS on your own deck |
| nothing recognised | runs the full pipeline with defaults |

Give the case a name (optional) → **Process**. Stages chain automatically and
the page refreshes while they run.

---

## 5. Collect the output

Open the case and click **⬇ Download results (.zip)**. You get:

```
geos_case\
  case.vtm                  multi-block container GEOS reads
  main.vtu                  rock matrix (tetrahedra, region attribute, GlobalIds)
  fracture.vtu              explicit fracture surfaces (triangles, aperture,
                            fracture_id, collocated_nodes)
  geos_dfn_fractures.xml    conformal GEOS deck
geos_case_edfm\
  geos_dfn_edfm.xml         EDFM GEOS deck (the runnable one today)
output\                     dfnWorks files produced or uploaded
```

The **Artifacts** table lists each generated file; **Files** browses everything;
`log` next to any job shows the full stdout for diagnosis.

> `geos_case_edfm\geos_dfn_edfm.xml` is the deck to use: it represents the
> whole fracture network as embedded surface elements inside the rock matrix.

---

## 6. Optional — also run GEOS

Stage *3 · Run GEOS* needs a GEOS binary (GEOS ships no Windows build):

* **WSL2** — build once inside Ubuntu-on-WSL, then point *GEOS executable* at
  the Linux path and set *GEOS backend* to `native`;
* **Docker** — build a GEOS image once and set *GEOS backend* = `docker`,
  *GEOS image* = your tag, *GEOS executable* = `/opt/geos/bin/geosx`.

Step-by-step commands are in `docs\INSTALL_windows.md` §5. Without it,
everything up to the decks still works.

When it runs, GEOS writes `*.pvd` + per-step `*.vtu` files; they appear under
**Artifacts** and in the results ZIP.

---

## 7. If something goes wrong

| Symptom | Fix |
|---|---|
| `docker: command not found` | Start Docker Desktop and reopen PowerShell |
| Stage 1: *no intersecting fractures* | Enlarge fractures or lower *Mesh h* in the case form |
| Stage 1: `MO DOES NOT EXIST: mo_poisson_pts` | Using a released LaGriT; switch backend to `docker` |
| Stage 3: *GEOS executable is not configured* | Expected without step 6 |
| Output files owned by `root` | Run the case from Docker Desktop's shared drive, or `docker run --rm -v "%cd%":/w ees16/dfnworks:latest chown -R 1000:1000 /w` |
| Panel port busy | `python run_panel.py --port 9000` |

---

*Command-line equivalents and the full reference: `docs\USER_GUIDE.md`,
`docs\INSTALL_windows.md`, `report\feasibility_report.md`.*
