# Installation & operation — Windows

> **New here?** Start with the 3-page
> [`TUTORIAL_windows.pdf`](TUTORIAL_windows.pdf) (input → results). This file
> is the reference for every option below.

The workbench is developed on Ubuntu and runs on Windows **without code
changes**. Two levels of support:

| Stage | Windows support |
|---|---|
| Management panel (UI, file upload/download, logs, DB) | ✔ native (pure Python) |
| dfnWorks→GEOS converters | ✔ native (pure Python + numpy) |
| dfnWorks generation/meshing | ✔ via **Docker Desktop** (recommended) or native LaGriT (partial) |
| GEOS solver | WSL2 (native Linux) or Docker; no Windows build exists |
| Converted *conformal* deck | generated, but needs a split matrix (see report §6.3) |
| Converted *EDFM* deck | ✔ runs today (executed 49-step PoC) |

## 0. Fast path (5 commands)

```bat
pip install numpy
docker pull ees16/dfnworks:latest
cd dfn-geos-workbench
python run_panel.py
:: open http://localhost:8765 → Quick process → drop a ZIP → Process
```

In **Settings** set *dfnWorks backend* = `docker`. Everything else is optional.

## 1. Prerequisites

1. **Python 3.10+** from python.org (tick *Add to PATH*). `numpy` is required
   by the converters/driver: `pip install numpy`.
2. **Docker Desktop** (uses WSL2 backend) — recommended path for dfnWorks.
3. Git for Windows (to clone the repos).

## 2. Get the projects

```bat
git clone https://github.com/lanl/dfnWorks.git
git clone https://github.com/GEOS-DEV/GEOS.git
docker pull ees16/dfnworks:latest
```

## 3. Run the panel

```bat
cd dfn-geos-workbench
python run_panel.py --port 8765
:: open http://localhost:8765
```

In **Settings**:

* set *dfnWorks backend* to `docker` (image `ees16/dfnworks:latest`);
* set *dfnworks_path* to your `dfnWorks` checkout (used by the generated
  drivers when running native);
* leave `geos_exe` empty unless you have a GEOS build (WSL2 path or remote).

## 4. Native dfnWorks on Windows (optional, partial)

* LaGriT provides a Windows build
  (`lagrit-windows-cygwin-no-exodus.exe`, LaGriT v3.3.2 release). Without
  Exodus, the **conforming DFM mesh** stage is unavailable on native Windows —
  use the docker backend for the full pipeline, or WSL2.
* The dfnWorks C++ helpers compile with MinGW/MSVC (`DFNGen`, `DFNTrans`,
  `CPP_correct_volumes`, `DFN_Mesh_Connectivity_Test` each ship a makefile).
* pydfnworks installs normally: `pip install -r dfnWorks\pydfnworks\requirements.txt`
  and `pip install .\dfnWorks\pydfnworks`.
* Create `%USERPROFILE%\.dfnworksrc` with the same JSON keys as on Ubuntu
  (use Windows paths, e.g. `C:\\Users\\you\\dfnWorks\\`).

## 5. GEOS on Windows

GEOS is built for Linux and ships **no Windows binary** (its Docker Hub images
are toolchain images, not a ready-to-run solver). Two workable options:

### 5a. Run the whole panel inside WSL2 (recommended)

This is the simplest route: inside WSL the workbench is just a Linux app.

```bat
wsl --install -d Ubuntu
:: then, inside Ubuntu:
::   follow docs/INSTALL_ubuntu.md exactly (git clone, pip install numpy,
::   build GEOS, python run_panel.py)
```

Open <http://localhost:8765> from Windows — WSL2 forwards the port. Cases are
created inside the WSL filesystem, which is also much faster than `/mnt/c`.

### 5b. Native Windows panel + GEOS in a container

The panel supports `geos_backend = docker`. You need an image that contains a
built `geosx`:

```bat
:: 1. build once (adapt paths); this is the command pair that was validated
docker run -d --name geosbuild geosx/ubuntu24.04-gcc13:364-1112 sleep infinity
docker cp GEOS geosbuild:/opt/GEOS
docker exec geosbuild bash -lc "git config --global --add safe.directory '*' && cd /opt/GEOS && git submodule update --init --recursive && python3 scripts/config-build.py -hc /spack-generated.cmake -bt Release -bp /opt/geos-build -ip /opt/geos-install -DENABLE_HYPRE=ON -DENABLE_TRILINOS=OFF -DGEOS_LA_INTERFACE=Hypre -DENABLE_TESTS=OFF -DENABLE_EXAMPLES=OFF -DENABLE_BENCHMARKS=OFF -DDISABLE_UNIT_TESTS=ON"
docker exec geosbuild bash -lc "cd /opt/geos-build && make -j4 geosx"
docker commit geosbuild dfn-geos:1.1 && docker rm -f geosbuild
```

Then in **Settings**: *GEOS backend* = `docker`, *GEOS docker image* =
`dfn-geos:1.1`, *GEOS executable* = `/opt/geos-build/bin/geosx`.

Notes from the reference build (Ubuntu 24.04, TPL tag `364-1112`):

* HPCReact must stay **ON** (it is included unconditionally by
  `ReactiveSinglePhaseFluid.hpp`); build only the `geosx` target, not
  `install`/`all`, otherwise HPCReact unit tests pull in gtest.
* `-j4` is a safe default under Docker Desktop's default memory; give Docker
  12 GB+ and raise to `-j6` if you want it faster.
* Expect 30–60 minutes. The resulting binary is
  `/opt/geos-build/bin/geosx` (~324 KB launcher + shared libraries).

Without a GEOS binary you still get every model artifact (mesh + decks); only
stage *3 · Run GEOS* is unavailable.

## 6. Notes

* Paths in generated GEOS XML files are **relative** to the XML location, so
  cases move freely between Ubuntu and Windows.
* All text outputs use LF line endings; editors on Windows handle this fine.
