"""Background job runner: stages executed as subprocesses with log capture."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import Config
from .db import Database
from .ingest import is_runnable_deck

# stage names
STAGE_DFN_MESH = "dfn_mesh"
STAGE_CONVERT = "convert_to_geos"
STAGE_GEOS_RUN = "run_geos"

# Default location of the GEOS binary inside the geos docker image (the image
# used by this project installs the build tree at /opt/geos).
GEOS_IN_CONTAINER = "/opt/geos/bin/geosx"

# External files a deck points at: mesh files (<VTKMesh file="..."/>) and the
# data tables used by constitutive models (tableFiles="{ a.txt, b.txt }").
_FILE_ATTR_RE = re.compile(
    r"\b(file|files|tableFiles|rockTableFiles|fluidTableFiles|voxelFile|"
    r"coordinateFiles|particleFile|OBLOperatorsTableFile)\s*=\s*\"([^\"]*)\"",
    re.I)
_INCLUDE_RE = re.compile(r"<File\b[^>]*\bname=\"([^\"]+)\"")


class JobRunner:
    def __init__(self, config: Config, db: Database, cases_root: Path):
        self.config = config
        self.db = db
        self.cases_root = Path(cases_root)
        self._threads: dict[int, threading.Thread] = {}
        self._procs: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._recover()

    # ------------------------------------------------------------- recovery --
    def _recover(self) -> None:
        """Mark jobs that were running when the panel stopped as failed."""
        for row in self.db.running_jobs():
            self.db.update_job(row["id"], status="failed",
                               ended_at=time.time(), returncode=-1,
                               details={"error": "panel restarted during job"})

    # --------------------------------------------------------------- control --
    def submit(self, case_id: int, stage: str, details: dict | None = None,
               chain: list[str] | None = None) -> int:
        backend = ""
        if stage == STAGE_DFN_MESH:
            backend, _img = self.config.resolve_backend("dfnworks")
        elif stage == STAGE_GEOS_RUN:
            backend, _img = self.config.resolve_backend("geos")
        else:
            backend = "native"  # conversion runs natively (numpy only)
        details = dict(details or {})
        if chain:
            details["chain"] = list(chain)
        job_id = self.db.create_job(case_id, stage, backend=backend,
                                    details=details)
        t = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        self._threads[job_id] = t
        t.start()
        return job_id

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            proc.terminate()
            return True
        return False

    # ----------------------------------------------------------------- runs --
    def _run(self, job_id: int) -> None:
        job = self.db.get_job(job_id)
        case = self.db.get_case(job["case_id"])
        case_dir = self.cases_root / case["name"]
        log_path = case_dir / "logs" / f"job_{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.db.update_job(job_id, status="running", started_at=time.time(),
                           log_path=str(log_path))

        try:
            builder = STAGES[job["stage"]]
            argv, env, cwd, use_shell = builder(self.config, case, case_dir)
            backend = job["backend"]

            creationflags = 0
            if os.name == "nt":  # Windows: detach console windows
                creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

            # a stage may produce several commands (e.g. conformal + EDFM decks)
            commands = argv if argv and isinstance(argv[0], (list, tuple)) \
                else [argv]
            rc = 0
            with open(log_path, "a", encoding="utf-8") as logf:
                for cmd in commands:
                    if backend == "docker":
                        cmd, env = self._dockerize(list(cmd), env, case_dir,
                                                   job["stage"])
                    logf.write(f"$ {' '.join(cmd)}\n"
                               f"  (backend={backend}, cwd={cwd})\n\n")
                    logf.flush()
                    proc = subprocess.Popen(
                        cmd, cwd=str(cwd), env=env, stdout=logf,
                        stderr=subprocess.STDOUT,
                        shell=False, creationflags=creationflags)
                    with self._lock:
                        self._procs[job_id] = proc
                    rc = proc.wait()
                    if rc != 0:
                        break

            if backend == "docker" and job["stage"] != STAGE_GEOS_RUN:
                self._chown_case(case_dir)

            details = collect_artifacts(job["stage"], case_dir, self.config, rc)
            if rc == 0:
                self._register_artifacts(job["case_id"], job["stage"],
                                         case_dir, details)
            chain = list(job.get("details", {}).get("chain") or [])
            if rc == 0 and chain:
                details["chained_next"] = chain
            self.db.update_job(
                job_id, status="done" if rc == 0 else "failed",
                ended_at=time.time(), returncode=rc, details=details)
            if rc == 0 and chain:
                self.submit(job["case_id"], chain[0],
                            details={"chained_from": job_id},
                            chain=chain[1:])
        except Exception as exc:  # pragma: no cover - defensive
            with open(log_path, "a", encoding="utf-8") as logf:
                logf.write(f"\nPANEL ERROR: {type(exc).__name__}: {exc}\n")
            self.db.update_job(job_id, status="failed", ended_at=time.time(),
                               returncode=-1,
                               details={"error": f"{type(exc).__name__}: {exc}"})
        finally:
            with self._lock:
                self._procs.pop(job_id, None)

    def _register_artifacts(self, case_id: int, stage: str, case_dir: Path,
                            details: dict) -> None:
        """Expose the files a successful stage produced on the case page."""
        paths: list[str] = []
        if stage == STAGE_CONVERT:
            for sub, names in details.items():
                if isinstance(names, list):
                    paths.extend(f"{sub}/{n}" for n in names)
        elif stage == STAGE_GEOS_RUN:
            paths.extend(details.get("plots") or [])
        else:
            paths.extend(k for k, v in details.items() if isinstance(v, int))
        for rel in paths:
            p = case_dir / rel
            if p.is_file():
                self.db.add_artifact(case_id, stage, rel, p.stat().st_size)

    def _chown_case(self, case_dir: Path) -> None:
        """Restore host-user ownership of files written by a root container."""
        uid = getattr(os, "getuid", None)
        if uid is None or uid == 0:
            return
        image = self.config["dfnworks_docker_image"] or \
            "ees16/dfnworks:latest"
        try:
            proc = subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", "chown",
                 "-v", f"{case_dir}:/w", image,
                 "-R", f"{uid}:{os.getgid()}", "/w"],
                capture_output=True, timeout=900)
            if proc.returncode != 0:
                print(f"warning: could not restore ownership of "
                      f"{case_dir} (chown rc={proc.returncode})", flush=True)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"warning: chown step failed: {exc}", flush=True)

    def _dockerize(self, argv: list[str], env: dict, case_dir: Path,
                   stage: str) -> tuple[list[str], dict]:
        """Wrap a native command into a docker run invocation."""
        if stage in (STAGE_DFN_MESH, STAGE_CONVERT):
            image = self.config["dfnworks_docker_image"]
        else:
            # use the resolved image so a locally built dfn-geos image works
            # even when Settings leaves the image name blank
            _backend, image = self.config.resolve_backend("geos")
        workdir = "/app"
        inner = argv[:]
        # container python for dfnWorks stages
        if stage in (STAGE_DFN_MESH, STAGE_CONVERT):
            if inner[0].endswith("python") or inner[0].endswith("python3") \
                    or Path(inner[0]).name in ("python", "python3"):
                inner[0] = "python3"
        # translate absolute case paths to the mount point
        cased = str(case_dir)
        inner = [a.replace(cased, workdir) if a.startswith(cased) else a
                 for a in inner]
        # the container carries its own dependencies; drop host PYTHONPATH
        env = {k: v for k, v in env.items()
               if k != "PYTHONPATH" and not k.startswith("LAGRIT")}
        argv = ["docker", "run", "--rm", "-v", f"{case_dir}:{workdir}",
                "-w", workdir]
        # The GEOS stage only reads the deck and writes plain files, so it can
        # run as the host user: outputs stay user-owned and need no chown.
        if stage == STAGE_GEOS_RUN and getattr(os, "getuid", lambda: 0)() != 0:
            argv += ["--user", f"{os.getuid()}:{os.getgid()}",
                     "-e", "HOME=/tmp"]
        argv += [image] + inner
        # NOTE: the container runs as root because pydfnworks writes an
        # .install_date marker into its site-packages at import time (which a
        # non-root user cannot do).  File ownership on the host is restored
        # after the run by _chown_case().
        return argv, env


# ------------------------------------------------------------------ stages --
def _base_env(config: Config) -> dict:
    env = dict(os.environ)
    py_entries = config.pythonpath_entries()
    if py_entries:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(py_entries +
                                            ([existing] if existing else []))
    # pydfnworks reads ~/.dfnworksrc; expose the tool paths for driver scripts
    if config["lagrit_exe"]:
        env["LAGRIT_EXE"] = config["lagrit_exe"]
    if config["dfnworks_path"]:
        env["dfnWorks_PATH"] = config["dfnworks_path"]
    return env


def stage_dfn_mesh(config: Config, case: dict, case_dir: Path):
    """Generate the dfnWorks driver from case params and run it."""
    from .pipeline import write_driver_script
    params = case.get("params") or {}
    driver = write_driver_script(case_dir, case["name"], params)
    python = config["python_exe"] or sys.executable
    return [python, str(driver)], _base_env(config), case_dir, False


def stage_convert(config: Config, case: dict, case_dir: Path):
    """Convert dfnWorks outputs into a GEOS case (VTM + XML decks).

    Searches the whole case directory for the dfnWorks outputs, so it works
    both for panel-generated cases and for uploaded/extracted archives.
    Produces the conformal case when a DFM mesh is present, and the EDFM deck
    whenever a DFN job directory (params.txt / polys / full_mesh.inp) exists.
    """
    from .ingest import resolve_dfn_outputs
    conv_dir = Path(__file__).resolve().parent.parent / "conversion"
    python = sys.executable
    dfm_dir, job_dir = resolve_dfn_outputs(case_dir)

    commands = []
    if dfm_dir is not None:
        commands.append([python, str(conv_dir / "dfn_to_geos.py"),
                         "--dfm-dir", str(dfm_dir),
                         "--out", str(case_dir / "geos_case")])
    if job_dir is not None:
        commands.append([python, str(conv_dir / "poly_to_geos_edfm.py"),
                         "--job-dir", str(job_dir),
                         "--out", str(case_dir / "geos_case_edfm")])
    if not commands:
        raise RuntimeError(
            "no dfnWorks outputs found in the case (expected full_mesh.inp / "
            "params.txt / polys/ and optional dfm_mesh/dfm_tet_mesh.inp)")
    return commands, _base_env(config), case_dir, False


def _resolve_deck(case: dict, case_dir: Path) -> Path | None:
    """The deck this case should run: uploaded one first, then generated."""
    params = case.get("params") or {}
    deck = str(params.get("deck") or "").strip()
    if deck:
        p = case_dir / deck
        if p.is_file():
            return p
    candidates = [case_dir / "geos_case_edfm" / "geos_dfn_edfm.xml",
                  case_dir / "geos_case" / "geos_dfn_fractures.xml"]
    # EDFM first: it is the path proven end-to-end (the conformal deck needs a
    # fracture-split matrix, see report §6.3).  Anything the user uploaded is
    # considered after the generated decks, shallow files first, and XML
    # fragments (`*_base.xml`, files that only <Included> others) are skipped.
    candidates += sorted(case_dir.rglob("geos_dfn_*.xml"))
    candidates += sorted(
        (p for p in case_dir.rglob("*.xml") if is_runnable_deck(p)),
        key=lambda p: (len(p.relative_to(case_dir).parts), str(p)))
    return next((p for p in candidates
                 if p.exists() and is_runnable_deck(p)), None)


def _split_refs(value: str) -> list[str]:
    """Split ``"a.txt"`` or ``"{ a.txt, b.txt }"`` into plain file names."""
    value = value.strip().strip("{}").strip()
    return [v.strip().strip("'\"") for v in re.split(r"[,\s]+", value)
            if v.strip()]


def _missing_input_files(xml: Path, case_dir: Path) -> list[str]:
    """Files a deck points at that are not in the case (relative to it)."""
    try:
        text = xml.read_text(errors="ignore")
    except OSError:
        return []
    refs: list[str] = []
    for _attr, value in _FILE_ATTR_RE.findall(text):
        refs.extend(_split_refs(value))
    refs.extend(_INCLUDE_RE.findall(text))
    missing = []
    for ref in refs:
        ref = ref.strip()
        if not ref or ref.startswith(("/", "\\")) or "://" in ref:
            continue          # absolute container path or remote URL
        if (xml.parent / ref).is_file() or (case_dir / ref).is_file():
            continue
        missing.append(ref)
    return sorted(set(missing))


def stage_geos_run(config: Config, case: dict, case_dir: Path):
    """Run GEOS on the generated or uploaded input deck."""
    geos = (config["geos_exe"] or "").strip()
    backend, image = config.resolve_backend("geos")
    if backend == "docker":
        if not image:
            raise RuntimeError(
                "GEOS is set to run in Docker, but no image is configured. "
                "Build one once with 'setup_windows.ps1 -WithGeos' (or "
                "'docker build' on Linux), then set Settings -> 'GEOS docker "
                "image' to dfn-geos:1.1 -- or switch 'GEOS backend' to auto.")
        # The executable path inside the image; a host-style path (Windows
        # drive letter, or one that does not exist in the container) would be
        # wrong here, so use the default location unless an absolute POSIX
        # path was given explicitly.
        if not geos or not geos.startswith("/"):
            geos = GEOS_IN_CONTAINER
    if not geos:
        raise RuntimeError(
            "GEOS is not configured, so the deck cannot be run. Either set "
            "Settings -> 'GEOS backend' = docker (an image such as "
            "dfn-geos:1.1 will be used automatically when it exists), or give "
            "the full path to the geosx executable.")
    xml = _resolve_deck(case, case_dir)
    if xml is None:
        raise RuntimeError("No GEOS input deck found; run the conversion "
                           "stage first (or upload an XML deck)")
    missing = _missing_input_files(xml, case_dir)
    if missing:
        raise RuntimeError(
            f"The deck '{xml.relative_to(case_dir)}' needs files that are not "
            "in this case: " + ", ".join(missing) + ". Upload them as well "
            "(loose files, keep them in the same folder as the XML). GEOS "
            "resolves these paths relative to the deck, so a single XML only "
            "works when it is self-contained (e.g. geos_dfn_edfm.xml, which "
            "builds its own mesh and needs no tables).")
    nproc = str(case.get("params", {}).get("geos_nproc", 1))
    if nproc and nproc != "1":
        return ["mpiexec", "-np", nproc, geos, "-i", str(xml)], \
            _base_env(config), xml.parent, False
    return [geos, "-i", str(xml)], _base_env(config), xml.parent, False


def collect_artifacts(stage: str, case_dir: Path, config: Config, rc: int) -> dict:
    """After a job finishes, register new artifacts in the DB (by convention)."""
    details: dict = {}
    if rc != 0:
        return details
    if stage == STAGE_DFN_MESH:
        out = case_dir / "output"
        for name in ("full_mesh.inp", "full_mesh.uge", "full_mesh_vol_area.uge",
                     "materialid.dat", "params.txt", "poly_info.dat"):
            p = out / name
            if p.exists():
                details[name] = p.stat().st_size
        if (out / "dfm_mesh" / "dfm_tet_mesh.inp").exists():
            details["dfm_mesh/dfm_tet_mesh.inp"] = \
                (out / "dfm_mesh" / "dfm_tet_mesh.inp").stat().st_size
    elif stage == STAGE_CONVERT:
        for sub in ("geos_case", "geos_case_edfm"):
            d = case_dir / sub
            if d.is_dir():
                details[sub] = sorted(p.name for p in d.iterdir())
    elif stage == STAGE_GEOS_RUN:
        plots = []
        for pat in ("**/*.pvd", "**/*.pvtu", "**/*.vtu", "**/*.vtp",
                    "**/*.vtk"):
            plots.extend(sorted(case_dir.glob(pat)))
        seen, keep = set(), []
        for p in plots:
            if p in seen:
                continue
            seen.add(p)
            keep.append(str(p.relative_to(case_dir)))
        details["plots"] = keep[:40]
        pvds = [p for p in keep if p.endswith(".pvd")]
        if pvds:
            details["time_series"] = pvds[0]
    return details


STAGES = {
    STAGE_DFN_MESH: stage_dfn_mesh,
    STAGE_CONVERT: stage_convert,
    STAGE_GEOS_RUN: stage_geos_run,
}
