#!/usr/bin/env python3
"""Docker command wrapping tests (host -> container path/exec translation).

Covers the Windows-host regressions: a host python.exe leaking into the
container command and backslash paths surviving the mount-point translation
("/app\\name" is a single name on Linux, so GEOS/pydfnworks never find it).

Run from the workbench root:  python3 tests/test_jobs.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import jobs  # noqa: E402


class _FakeConfig:
    """Just enough of Config for _dockerize (no docker probing)."""

    def __getitem__(self, key):
        return "ees16/dfnworks:latest" \
            if key == "dfnworks_docker_image" else ""

    def resolve_backend(self, _name):
        return "docker", "dfn-geos:1.1"


class _FakeDB:
    def running_jobs(self):
        return []


class ContainerPathTests(unittest.TestCase):
    def test_case_path_translated_with_posix_separators(self):
        cased = r"C:\proj\cases\test1"
        self.assertEqual(
            jobs._container_path(cased + r"\dfn_driver.py", cased),
            "/app/dfn_driver.py")
        self.assertEqual(
            jobs._container_path(cased + r"\geos_case\a.xml", cased),
            "/app/geos_case/a.xml")

    def test_case_dir_itself_translated(self):
        self.assertEqual(jobs._container_path(r"C:\proj\cases\test1",
                                              r"C:\proj\cases\test1"),
                         "/app")

    def test_unrelated_args_untouched(self):
        self.assertEqual(jobs._container_path("-i", r"C:\proj\cases\test1"),
                         "-i")
        self.assertEqual(jobs._container_path("/opt/geos/bin/geosx",
                                              r"C:\proj\cases\test1"),
                         "/opt/geos/bin/geosx")
        self.assertEqual(jobs._container_path(r"D:\other\f.txt",
                                              r"C:\proj\cases\test1"),
                         r"D:\other\f.txt")

    def test_posix_host_paths(self):
        self.assertEqual(jobs._container_path("/home/u/cases/test1/a.xml",
                                              "/home/u/cases/test1"),
                         "/app/a.xml")


class DockerizeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _runner(self, case_dir: Path) -> jobs.JobRunner:
        return jobs.JobRunner(_FakeConfig(), _FakeDB(), case_dir.parent)

    def test_windows_python_and_driver_path(self):
        """The regression from the Windows report: python.exe + /app\\driver."""
        cased = r"C:\dfn-project\dfn-geos-workbench\cases\test1"
        case_dir = Path(cased)
        runner = self._runner(case_dir)
        argv = [r"C:\Users\Iman\AppData\Local\Python\pythoncore-3.15-64"
                r"\python.exe",
                cased + r"\dfn_driver.py"]
        cmd, env = runner._dockerize(argv, {}, case_dir, jobs.STAGE_DFN_MESH)
        self.assertEqual(
            cmd[-2:], ["python3", "/app/dfn_driver.py"])
        self.assertEqual(cmd[0], "docker")
        self.assertIn("-w", cmd)
        self.assertEqual(cmd[cmd.index("-w") + 1], "/app")
        # the host interpreter must not appear anywhere in the command
        self.assertNotIn(argv[0], cmd)

    def test_geos_deck_path_uses_forward_slashes(self):
        cased = r"C:\dfn-project\dfn-geos-workbench\cases\test1"
        case_dir = Path(cased)
        runner = self._runner(case_dir)
        argv = ["/opt/geos/bin/geosx", "-i",
                cased + r"\compressible_single_phase_wells_1d.xml"]
        cmd, _env = runner._dockerize(argv, {}, case_dir,
                                      jobs.STAGE_GEOS_RUN)
        self.assertEqual(
            cmd[-3:],
            ["/opt/geos/bin/geosx", "-i",
             "/app/compressible_single_phase_wells_1d.xml"])

    def test_python3_exe_and_versioned_names_swapped(self):
        case_dir = self.root / "case"
        case_dir.mkdir()
        runner = self._runner(case_dir)
        for exe in ("python", "python.exe", r"C:\py\python3.exe",
                    r"C:\py\python3.12"):
            argv = [exe, str(case_dir / "d.py")]
            cmd, _ = runner._dockerize(argv, {}, case_dir,
                                       jobs.STAGE_DFN_MESH)
            self.assertEqual(cmd[-2], "python3", exe)
            self.assertEqual(cmd[-1], "/app/d.py")

    def test_host_pythonpath_dropped(self):
        case_dir = self.root / "case"
        case_dir.mkdir()
        runner = self._runner(case_dir)
        _cmd, env = runner._dockerize(
            ["python3", str(case_dir / "d.py")],
            {"PATH": "/usr/bin", "PYTHONPATH": "/host/compat"},
            case_dir, jobs.STAGE_DFN_MESH)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env.get("PATH"), "/usr/bin")


if __name__ == "__main__":
    unittest.main()
