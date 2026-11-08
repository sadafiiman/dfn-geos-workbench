"""Panel configuration: JSON settings shared by the web UI and job runners.

The default location of the settings file is ``<panel-package>/../config.json``
(or the directory given through the ``DFN_GEOS_PANEL_HOME`` environment
variable).  All paths are stored as strings and interpreted with
``os.path``/``pathlib`` so the panel behaves identically on Ubuntu and Windows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
DEFAULT_HOME = Path(os.environ.get("DFN_GEOS_PANEL_HOME",
                                   PKG_DIR.parent)).resolve()

DEFAULTS = {
    # discovery roots (repos cloned next to the panel, by default)
    "dfnworks_path": "",          # dfnWorks repository (with pydfnworks/)
    "lagrit_exe": "",             # LaGriT executable
    "geos_exe": "",               # GEOS executable (optional)
    "python_exe": "",             # python to use for dfnWorks drivers ("" = sys.executable)
    # optional dependency shims + vendored networkx that let pydfnworks run
    # with a light environment (see compat/ and vendor/ in the workbench)
    "use_compat_pythonpath": True,
    # docker backend for dfnWorks (recommended on Windows)
    "dfnworks_docker_image": "ees16/dfnworks:latest",
    "dfnworks_backend": "auto",   # auto | native | docker
    "geos_backend": "auto",       # auto | native | docker (image name below)
    "geos_docker_image": "",
    "panel_port": 8765,
}


class Config:
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else DEFAULT_HOME
        self.path = self.home / "config.json"
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self._data.update(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                pass

    def save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True))

    def __getitem__(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key: str, value) -> None:
        self._data[key] = value

    @property
    def data(self) -> dict:
        return dict(self._data)

    def pythonpath_entries(self) -> list[str]:
        """Directories prepended to PYTHONPATH for dfnWorks driver jobs."""
        if not self["use_compat_pythonpath"]:
            return []
        base = PKG_DIR.parent
        entries = []
        for sub in ("compat", "vendor"):
            p = base / sub
            if p.is_dir():
                entries.append(str(p))
        dw = self["dfnworks_path"]
        if dw:
            py = Path(dw) / "pydfnworks"
            if py.is_dir():
                entries.append(str(py))
        return entries

    def detect_dfnworks(self) -> str:
        """Best-effort autodetection of the dfnWorks repository."""
        if self["dfnworks_path"] and Path(self["dfnworks_path"]).is_dir():
            return self["dfnworks_path"]
        for candidate in (self.home.parent / "dfnWorks",
                          self.home / "dfnWorks",
                          Path.home() / "dfnWorks"):
            if (candidate / "pydfnworks").is_dir():
                self["dfnworks_path"] = str(candidate)
                return str(candidate)
        return ""

    def detect_lagrit(self) -> str:
        if self["lagrit_exe"] and os.path.isfile(self["lagrit_exe"]):
            return self["lagrit_exe"]
        base = PKG_DIR.parent
        for cand in (base / "tools" / "lagrit", base / "tools" / "lagrit.exe",
                     base / "tools" / "lagrit_v33"):
            if cand.is_file():
                self["lagrit_exe"] = str(cand)
                return str(cand)
        return ""

    def resolve_backend(self, tool: str) -> tuple[str, str]:
        """Return (backend, image) for 'dfnworks' or 'geos'."""
        if tool == "dfnworks":
            backend = self["dfnworks_backend"]
            image = self["dfnworks_docker_image"]
            if backend == "auto":
                native_ok = bool(self.detect_dfnworks() and self.detect_lagrit())
                backend = "native" if native_ok else "docker"
            return backend, image
        backend = (self["geos_backend"] or "auto").lower()
        if backend == "auto":
            backend = "native" if self["geos_exe"] else (
                "docker" if self["geos_docker_image"] else "native")
        return backend, self["geos_docker_image"]
