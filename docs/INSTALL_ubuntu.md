# Installation & operation — Ubuntu (development platform)

## 1. Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git g++ make cmake docker.io
```

* **Python ≥ 3.10** — the panel needs only the standard library.
* **Docker** (recommended, see §3) gives a known-good dfnWorks toolchain.

## 2. Clone the two open-source projects

```bash
git clone https://github.com/lanl/dfnWorks.git
git clone https://github.com/GEOS-DEV/GEOS.git          # optional: XML templates/schema
```

## 3. dfnWorks toolchain

### Option A — Docker (recommended, works identically on Windows)

```bash
docker pull ees16/dfnworks:latest
```

No other dfnWorks setup is needed; the panel and the POC scripts can execute
the whole generation+meshing stage inside this image (`dfnworks_backend=auto`
falls back to docker when no native LaGriT is configured).

> **Caveat:** the image's LaGriT is *not* linked against Exodus, so
> `dump / exo` in the DFM stage fails — but all AVS/UCD outputs
> (`dfm_tet_mesh.inp`, `facets_f*.inp/table`) are still produced, and those
> are exactly what the converter consumes.

### Option B — native

1. Build the small dfnWorks C++ helpers:

   ```bash
   cd dfnWorks/DFNGen                 && make
   cd ../DFNTrans                     && make
   cd ../CPP_correct_volumes          && make
   cd ../DFN_Mesh_Connectivity_Test   && make
   ```

2. Install pydfnworks:

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r dfnWorks/pydfnworks/requirements.txt
   pip install ./dfnWorks/pydfnworks
   ```

3. LaGriT: **do not use the release binaries from the LaGriT GitHub page** —
   they lack the `poisson_disk` module required by current dfnWorks (verified;
   meshing fails with `MO DOES NOT EXIST: mo_poisson_pts`). Build LaGriT from
   source instead:

   ```bash
   git clone https://github.com/LANL/LaGriT.git && cd LaGriT
   make static WITH_EXODUS=0        # add Exodus libs (seacas) for full DFM
   cp src/lagrit /path/to/workbench/tools/lagrit
   ```

   or extract the docker image's LaGriT (it has poisson_disk but no Exodus):

   ```bash
   id=$(docker create ees16/dfnworks:latest)
   docker cp $id:/dfnWorks/bin/lagrit ./tools/lagrit && docker rm $id
   ```

4. Create `~/.dfnworksrc`:

   ```json
   {
       "dfnworks_PATH": "/absolute/path/to/dfnWorks/",
       "LAGRIT_EXE": "/absolute/path/to/lagrit",
       "PETSC_DIR": "",
       "PETSC_ARCH": "",
       "PFLOTRAN_EXE": "",
       "FEHM_EXE": ""
   }
   ```

   (PFLOTRAN/FEHM are only needed for the flow/transport stages of dfnWorks,
   not for mesh generation or for the GEOS integration.)

## 4. GEOS

GEOS is built from source (see the GEOS Quick Start guide). On a laptop the
lightest useful configuration is serial/MIPI:

```bash
git clone https://github.com/GEOS-DEV/GEOS.git
cd GEOS && mkdir build && cd build
../scripts/build_uberenv.sh          # third-party libraries
cmake -C host-configs/<your>.cmake .. && make -j
```

Register the resulting `geos` binary path in the panel **Settings** page
(`geos_exe`). Without a GEOS binary the panel still performs stages 1–2
(dfnWorks meshing + conversion) and delivers the ready-to-run decks.

## 5. Run the panel

```bash
cd dfn-geos-workbench
python3 run_panel.py --port 8765
# open http://localhost:8765
```

Nothing else to install: the panel, the converters and the POC scripts use
only the Python standard library plus `numpy` (already present on Ubuntu).

## 6. Run the proof of concept (CLI variant)

```bash
cd dfn-geos-workbench/poc
PYTHONPATH=../compat:../vendor:../dfnWorks/pydfnworks python3 run_dfn_example.py
cd ../conversion
python3 dfn_to_geos.py      --dfm-dir ../poc/output/dfm_mesh --out ../poc/geos_case
python3 poly_to_geos_edfm.py --job-dir ../poc/output --out ../poc/geos_case_edfm
# then, with a GEOS build available (EDFM deck is the one that runs today):
geosx -i ../poc/geos_case_edfm/geos_dfn_edfm.xml
# the conformal deck loads but needs a split matrix (report §6.3):
#   geosx -i ../poc/geos_case/geos_dfn_fractures.xml
```

The 78-deck validation of GEOS' own samples and the exact GEOS build used are
documented in `validation/README.md`.
