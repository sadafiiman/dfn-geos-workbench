# Installation & operation — Windows

The workbench is developed on Ubuntu and runs on Windows **without code
changes**. Two levels of support:

| Stage | Windows support |
|---|---|
| Management panel (UI, file upload/download, logs, DB) | ✔ native (pure Python) |
| dfnWorks→GEOS converters | ✔ native (pure Python + numpy) |
| dfnWorks generation/meshing | ✔ via **Docker Desktop** (recommended) or native LaGriT (partial) |
| GEOS solver | via Docker or WSL2 (GEOS ships no Windows build) |

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

GEOS is developed for Linux/HPC; on Windows use one of:

* **WSL2**: build GEOS inside Ubuntu-on-WSL following `docs/INSTALL_ubuntu.md`,
  then point the panel's `geos_exe` to the WSL path
  (e.g. `wsl -e /home/you/GEOS/build/geos` — or run stage 3 from WSL);
* **Docker**: build a GEOS image from `GEOS/scripts/docker` and set
  *GEOS backend* = `docker` with the image name in Settings.

## 6. Notes

* Paths in generated GEOS XML files are **relative** to the XML location, so
  cases move freely between Ubuntu and Windows.
* All text outputs use LF line endings; editors on Windows handle this fine.
