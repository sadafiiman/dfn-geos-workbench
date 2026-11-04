# tools/

LaGriT executables are **not tracked in git** (binaries, and the released
upstream builds are known-incompatible with current dfnWorks anyway).

Recommended way to get a working LaGriT:

```bash
# from the official dfnWorks docker image (has poisson_disk, no Exodus):
id=$(docker create ees16/dfnworks:latest)
docker cp "$id":/dfnWorks/bin/lagrit ./lagrit && docker rm "$id"

# or build from source:
git clone https://github.com/LANL/LaGriT.git && cd LaGriT
make static WITH_EXODUS=0
cp src/lagrit /path/to/dfn-geos-workbench/tools/lagrit
```

Place the binary here as `tools/lagrit` (Linux/macOS) or `tools/lagrit.exe`
(Windows) and point `LAGRIT_EXE` in `~/.dfnworksrc` (or the panel Settings)
at it.  See `docs/INSTALL_ubuntu.md` / `docs/INSTALL_windows.md`.
