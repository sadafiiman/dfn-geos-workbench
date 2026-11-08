"""Background job runner: stages executed as subprocesses with log capture."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import Config
from .db import Database

# stage names
STAGE_DFN_MESH = "dfn_mesh"
STAGE_CONVERT = "convert_to_geos"
STAGE_GEOS_RUN = "run_geos"


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
        image = (self.config["dfnworks_docker_image"]
                 if stage in (STAGE_DFN_MESH, STAGE_CONVERT)
                 else self.config["geos_docker_image"])
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


def stage_geos_run(config: Config, case: dict, case_dir: Path):
    """Run GEOS on the generated input deck (searched anywhere in the case)."""
    geos = config["geos_exe"]
    if not geos:
        raise RuntimeError("GEOS executable is not configured (see Settings)")
    candidates = [case_dir / "geos_case_edfm" / "geos_dfn_edfm.xml",
                  case_dir / "geos_case" / "geos_dfn_fractures.xml"]
    # EDFM first: it is the path proven end-to-end (the conformal deck needs a
    # fracture-split matrix, see report §6.3).  Anything the user uploaded is
    # considered after the generated decks.
    candidates += sorted(case_dir.rglob("geos_dfn_*.xml"))
    candidates += sorted(case_dir.rglob("*.xml"))
    xml = next((p for p in candidates if p.exists()), None)
    if xml is None:
        raise RuntimeError("No GEOS input deck found; run the conversion "
                           "stage first (or upload an XML + mesh)")
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
