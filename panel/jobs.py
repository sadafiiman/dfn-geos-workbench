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
    def submit(self, case_id: int, stage: str, details: dict | None = None) -> int:
        backend = ""
        if stage == STAGE_DFN_MESH:
            backend, _img = self.config.resolve_backend("dfnworks")
        elif stage == STAGE_GEOS_RUN:
            backend, _img = self.config.resolve_backend("geos")
        else:
            backend = "native"  # conversion runs natively (numpy only)
        job_id = self.db.create_job(case_id, stage, backend=backend,
                                    details=details or {})
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

            if backend == "docker":
                argv, env = self._dockerize(argv, env, case_dir, job["stage"])

            creationflags = 0
            if os.name == "nt":  # Windows: detach console windows
                creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

            with open(log_path, "a", encoding="utf-8") as logf:
                logf.write(f"$ {' '.join(argv)}\n"
                           f"  (backend={backend}, cwd={cwd})\n\n")
                logf.flush()
                proc = subprocess.Popen(
                    argv, cwd=str(cwd), env=env, stdout=logf,
                    stderr=subprocess.STDOUT,
                    shell=False, creationflags=creationflags)
                with self._lock:
                    self._procs[job_id] = proc
                rc = proc.wait()

            if backend == "docker":
                self._chown_case(case_dir)

            self.db.update_job(
                job_id, status="done" if rc == 0 else "failed",
                ended_at=time.time(), returncode=rc,
                details=collect_artifacts(job["stage"], case_dir,
                                          self.config, rc))
        except Exception as exc:  # pragma: no cover - defensive
            with open(log_path, "a", encoding="utf-8") as logf:
                logf.write(f"\nPANEL ERROR: {type(exc).__name__}: {exc}\n")
            self.db.update_job(job_id, status="failed", ended_at=time.time(),
                               returncode=-1,
                               details={"error": f"{type(exc).__name__}: {exc}"})
        finally:
            with self._lock:
                self._procs.pop(job_id, None)

    def _chown_case(self, case_dir: Path) -> None:
        """Restore host-user ownership of files written by a root container."""
        uid = getattr(os, "getuid", None)
        if uid is None or uid == 0:
            return
        image = self.config["dfnworks_docker_image"] or \
            "ees16/dfnworks:latest"
        try:
            subprocess.run(["docker", "run", "--rm", "-v", f"{case_dir}:/w",
                            image, "chown", "-R", f"{uid}:{os.getgid()}", "/w"],
                           capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            pass

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
                "-w", workdir, image] + inner
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
    """Convert dfnWorks outputs into a GEOS case (VTM + XML decks)."""
    conv_dir = Path(__file__).resolve().parent.parent / "conversion"
    python = sys.executable
    dfm = case_dir / "output" / "dfm_mesh"
    if (dfm / "dfm_tet_mesh.inp").exists():
        argv = [python, str(conv_dir / "dfn_to_geos.py"),
                "--dfm-dir", str(dfm),
                "--out", str(case_dir / "geos_case")]
    else:
        argv = [python, str(conv_dir / "poly_to_geos_edfm.py"),
                "--job-dir", str(case_dir / "output"),
                "--out", str(case_dir / "geos_case_edfm")]
    return argv, _base_env(config), case_dir, False


def stage_geos_run(config: Config, case: dict, case_dir: Path):
    """Run GEOS on the generated input deck."""
    geos = config["geos_exe"]
    if not geos:
        raise RuntimeError("GEOS executable is not configured (see Settings)")
    xml = case_dir / "geos_case" / "geos_dfn_fractures.xml"
    if not xml.exists():
        xml = case_dir / "geos_case_edfm" / "geos_dfn_edfm.xml"
    if not xml.exists():
        raise RuntimeError("No GEOS input deck found; run the conversion stage first")
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
        vtks = sorted(case_dir.glob("**/*.pvtu")) + \
            sorted(case_dir.glob("**/*.vtk"))
        details["plots"] = [str(p.relative_to(case_dir)) for p in vtks][:20]
    return details


STAGES = {
    STAGE_DFN_MESH: stage_dfn_mesh,
    STAGE_CONVERT: stage_convert,
    STAGE_GEOS_RUN: stage_geos_run,
}
