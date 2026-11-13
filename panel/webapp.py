"""The dfn-GEOS Workbench web panel — standard library only.

Run with:  python run_panel.py [--port 8765]

Features
--------
* Cases: create dfnWorks/GEOS projects with parameters (domain, fracture
  families or user fractures, mesh resolution, seed...).
* Pipelines: one-click jobs — dfnWorks generation+meshing (native or via the
  official docker image), dfnWorks→GEOS conversion, GEOS run.
* File management: upload inputs, browse/download/preview every file of a
  case, artifacts registered automatically after each job.
* Live job logs with auto-refresh.
* Settings: paths to dfnWorks, LaGriT, GEOS, execution backends.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from .db import Database
from . import render as R
from . import dfn_input
from . import ingest
from . import preview as PV
from .jobs import (STAGE_CONVERT, STAGE_DFN_MESH, STAGE_GEOS_RUN, JobRunner)
from .pipeline import DEFAULT_FAMILIES

PKG_DIR = Path(__file__).resolve().parent
WORKBENCH = PKG_DIR.parent
MAX_UPLOAD = 512 * 1024 * 1024
TEXT_EXTS = {".txt", ".dat", ".xml", ".inp", ".uge", ".md", ".json", ".log",
             ".py", ".csv", ".mlgi", ".lgi", ".yaml", ".yml", ".sty", ".h5s"}

# These are text, but they are not readable data — they describe 3-D meshes
# and time series that only a mesh viewer (ParaView/VisIt) can draw.
MESH_EXTS = {".pvd", ".vtm", ".vtu", ".vtp", ".vtk", ".pvtu", ".pvtk"}

_STAGE_LABELS = {
    STAGE_DFN_MESH: ("1 · dfnWorks mesh", "dfnGen → LaGriT → full_mesh"),
    STAGE_CONVERT: ("2 · Convert → GEOS", "VTK multi-block + XML decks"),
    STAGE_GEOS_RUN: ("3 · Run GEOS", "single-phase fracture flow"),
}

# ---------------------------------------------------------------- DFN editor --
# "Size" changes meaning with the radius distribution (see _family_row_html).
_FAMILY_DIST_HELP = (
    "Size depends on the distribution: <b>constant</b> → size itself · "
    "<b>log_normal</b> → log mean (SD = log std) · <b>tpl</b> → alpha · "
    "<b>exp</b> → exp mean. Min/Max bound the sampled sizes. Probabilities "
    "are relative weights (they don't need to sum to 1 — dfnGen rescales "
    "them); the fracture count comes from “Number of fractures” (nPoly). "
    "<b>Kappa</b> is the Fisher orientation concentration — leave blank for "
    "dfnWorks' default of 20 (one value per family is required).")

_BLANK_FAMILY = {"shape": "rect", "distribution": "constant",
                 "constant": 2.0, "aspect": 1.0, "probability": 1.0,
                 "trend": 0.0, "plunge": 0.0, "beta_distribution": 0,
                 "beta": 0.0}


def default_params() -> dict:
    """The parameter set a brand-new case gets; also used by the editor's
    “↺ Reset to defaults” button so both stay in sync."""
    return {
        "domain": [6.0, 6.0, 6.0],
        "h": 0.35,
        "seed": 42,
        "ncpu": 4,
        "mesh_dfm": True,
        "n_poly": 24,
        "boundary_faces": [1, 1, 0, 0, 0, 0],
        "ignore_boundary_faces": True,
        "families": [dict(f) for f in DEFAULT_FAMILIES],
        "fractures": [],
    }


def _g(value, default: str = "") -> str:
    """Render a number for an <input value=...> (%g), or the default."""
    if value is None or value == "":
        return default
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _num_field(form: dict, key: str, label: str, errors: list,
               cast=float, default=None):
    raw = (form.get(key) or "").strip()
    if raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        errors.append(f"{label}: “{R.esc(raw)}” is not a number")
        return default


def _parse_vec3(raw: str, default, label: str, errors: list) -> list:
    raw = (raw or "").strip().strip("{}")
    if not raw:
        return list(default)
    parts = [p for p in re.split(r"[,;\s]+", raw) if p]
    if len(parts) != 3:
        errors.append(f"{label}: need 3 numbers x,y,z (got “{R.esc(raw)}”)")
        return list(default)
    try:
        return [float(p) for p in parts]
    except ValueError:
        errors.append(f"{label}: “{R.esc(raw)}” is not a list of numbers")
        return list(default)


def _family_from_form(form: dict, i: int, errors: list) -> dict | None:
    """One fracture-family row (fields ``fam<i>_*``) -> family dict."""
    label = f"Family {i + 1}"
    dist = form.get(f"fam{i}_dist") or "constant"
    if dist not in ("constant", "log_normal", "tpl", "exp"):
        dist = "constant"
    fam: dict = {"shape": form.get(f"fam{i}_shape") or "rect",
                 "distribution": dist}
    size = _num_field(form, f"fam{i}_size", f"{label} size", errors)
    if size is not None:
        if dist == "constant":
            fam["constant"] = size
        elif dist == "log_normal":
            fam["log_mean"] = size
        elif dist == "tpl":
            fam["alpha"] = size
        else:
            fam["exp_mean"] = size
    if dist == "log_normal":
        sd = _num_field(form, f"fam{i}_sd", f"{label} log std", errors)
        if sd is not None:
            fam["log_std"] = sd
    mn = _num_field(form, f"fam{i}_min", f"{label} min", errors)
    mx = _num_field(form, f"fam{i}_max", f"{label} max", errors)
    if dist != "constant":
        if mn is not None:
            fam["min_radius"] = mn
        if mx is not None:
            fam["max_radius"] = mx
    for key, dkey in (("aspect", "aspect"), ("prob", "probability"),
                      ("trend", "trend"), ("plunge", "plunge")):
        v = _num_field(form, f"fam{i}_{key}", f"{label} {key}", errors)
        if v is not None:
            fam[dkey] = v
    kappa = _num_field(form, f"fam{i}_kappa", f"{label} kappa", errors)
    if kappa is not None:
        fam["kappa"] = kappa
    if form.get(f"fam{i}_bd"):
        fam["beta_distribution"] = 1
        beta = _num_field(form, f"fam{i}_beta", f"{label} beta", errors,
                          default=0.0)
        fam["beta"] = beta if beta is not None else 0.0
    else:
        fam["beta_distribution"] = 0
        fam["beta"] = 0.0
    return fam


def _uf_from_form(form: dict, i: int, errors: list) -> dict | None:
    """One user-fracture row (fields ``uf<i>_*``) -> fracture dict, or None
    when the row was left untouched."""
    label = f"Fracture {i + 1}"
    raw_r = (form.get(f"uf{i}_radii") or "").strip()
    raw_c = (form.get(f"uf{i}_ctr") or "").strip()
    raw_n = (form.get(f"uf{i}_nrm") or "").strip()
    if not (raw_r or raw_c or raw_n):
        return None
    uf: dict = {"shape": form.get(f"uf{i}_shape") or "rect"}
    try:
        uf["radii"] = float(raw_r) if raw_r else 0.5
    except ValueError:
        errors.append(f"{label}: radius “{R.esc(raw_r)}” is not a number")
        uf["radii"] = 0.5
    aspect = (form.get(f"uf{i}_aspect") or "").strip()
    if aspect:
        try:
            uf["aspect_ratio"] = float(aspect)
        except ValueError:
            errors.append(f"{label}: aspect “{R.esc(aspect)}” is not a number")
    uf["translation"] = _parse_vec3(raw_c, [0.0, 0.0, 0.0],
                                    f"{label} center", errors)
    uf["normal"] = _parse_vec3(raw_n, [0.0, 0.0, 1.0],
                               f"{label} normal", errors)
    perm = (form.get(f"uf{i}_perm") or "").strip()
    if perm:
        try:
            uf["permeability"] = float(perm)
        except ValueError:
            errors.append(f"{label}: permeability “{R.esc(perm)}” is not a "
                          "number")
    return uf


def _params_from_form(form: dict, base: dict) -> tuple[dict, list[str]]:
    """Merge an *Edit DFN* form over the saved case parameters."""
    errors: list[str] = []
    p = dict(base or {})
    p.pop("dfn_unmapped", None)
    p.pop("dfn_notes", None)
    p.pop("dfn_source", None)

    dom = [_num_field(form, k, lbl, errors)
           for k, lbl in (("dx", "Domain X"), ("dy", "Domain Y"),
                          ("dz", "Domain Z"))]
    if all(v is not None for v in dom):
        p["domain"] = [float(v) for v in dom]
    h = _num_field(form, "h", "Mesh h", errors)
    if h is not None:
        p["h"] = h
    seed = _num_field(form, "seed", "Seed", errors, int)
    if seed is not None:
        p["seed"] = seed
    ncpu = _num_field(form, "ncpu", "Threads", errors, int)
    if ncpu is not None:
        p["ncpu"] = max(1, ncpu)
    n_poly_raw = _num_field(form, "n_poly", "Number of fractures", errors, int)
    # blank = the driver default of 24; explicit values must be valid later
    n_poly = int(n_poly_raw) if n_poly_raw is not None else 24

    bf_raw = (form.get("boundary_faces") or "").strip().strip("{}")
    if bf_raw:
        parts = [x for x in re.split(r"[,\s]+", bf_raw) if x]
        try:
            bfaces = [int(float(x)) for x in parts]
        except ValueError:
            bfaces = []
        if len(bfaces) == 6:
            p["boundary_faces"] = bfaces
        else:
            errors.append("Boundary faces: need six 0/1 values, e.g. "
                          "1,1,0,0,0,0")
    p["ignore_boundary_faces"] = bool(form.get("ignore_boundary_faces"))
    p["mesh_dfm"] = bool(form.get("mesh_dfm"))

    try:
        fam_count = min(int(form.get("fam_count") or 0), 200)
    except ValueError:
        fam_count = 0
    p["families"] = [f for i in range(fam_count)
                     if not form.get(f"fam{i}_del")
                     and (f := _family_from_form(form, i, errors)) is not None]
    try:
        uf_count = min(int(form.get("uf_count") or 0), 500)
    except ValueError:
        uf_count = 0
    p["fractures"] = [f for i in range(uf_count)
                      if not form.get(f"uf{i}_del")
                      and (f := _uf_from_form(form, i, errors)) is not None]

    # nPoly only matters when the driver uses stochastic families (families
    # present, or the default families when there are no user fractures).
    # dfnGen rejects nPoly = 0, so require >= 1 there.
    stochastic = bool(p["families"]) or not p["fractures"]
    if stochastic and n_poly < 1:
        errors.append("Number of fractures (nPoly): must be at least 1 "
                      "(leave blank for the default of 24)")
    else:
        p["n_poly"] = n_poly
    return p, errors


def _family_row_html(i: int, fam: dict) -> str:
    dist = fam.get("distribution", "constant")

    def val(*keys):
        for k in keys:
            v = fam.get(k)
            if v not in (None, ""):
                return _g(v)
        return ""

    size = {"constant": val("constant"), "log_normal": val("log_mean"),
            "tpl": val("alpha"), "exp": val("exp_mean")}.get(dist, "")
    opts = "".join(
        f'<option value="{d}"{" selected" if d == dist else ""}>{lbl}</option>'
        for d, lbl in (("constant", "constant"), ("log_normal", "log_normal"),
                       ("tpl", "tpl (power-law)"), ("exp", "exponential")))
    shapes = "".join(
        f'<option value="{s}"{" selected" if s == fam.get("shape", "rect") else ""}>{s}</option>'
        for s in ("rect", "ell"))
    return f"""<tr>
      <td><select name="fam{i}_shape">{shapes}</select></td>
      <td><select name="fam{i}_dist">{opts}</select></td>
      <td><input name="fam{i}_size" value="{size}"></td>
      <td><input name="fam{i}_sd" value="{_g(fam.get('log_std'))}"></td>
      <td><input name="fam{i}_min" value="{_g(fam.get('min_radius'))}"></td>
      <td><input name="fam{i}_max" value="{_g(fam.get('max_radius'))}"></td>
      <td><input name="fam{i}_aspect" value="{_g(fam.get('aspect'))}"></td>
      <td><input name="fam{i}_prob" value="{_g(fam.get('probability'))}"></td>
      <td><input name="fam{i}_trend" value="{_g(fam.get('trend'))}"></td>
      <td><input name="fam{i}_plunge" value="{_g(fam.get('plunge'))}"></td>
      <td><input name="fam{i}_kappa" value="{_g(fam.get('kappa'))}"
           placeholder="20"
           title="Fisher kappa — orientation concentration (blank = default 20)"></td>
      <td><input type="checkbox" name="fam{i}_bd"
           {"checked" if fam.get("beta_distribution") else ""}></td>
      <td><input name="fam{i}_beta" value="{_g(fam.get('beta'))}"></td>
      <td><input type="checkbox" name="fam{i}_del" title="remove row"></td>
    </tr>"""


def _uf_row_html(i: int, uf: dict) -> str:
    def vec(key, default):
        v = uf.get(key)
        if not v:
            return default
        return ",".join(_g(x) for x in v)

    shapes = "".join(
        f'<option value="{s}"{" selected" if s == uf.get("shape", "rect") else ""}>{s}</option>'
        for s in ("rect", "ell", "poly"))
    return f"""<tr>
      <td><select name="uf{i}_shape">{shapes}</select></td>
      <td><input name="uf{i}_radii" value="{_g(uf.get('radii'))}"></td>
      <td><input name="uf{i}_aspect" value="{_g(uf.get('aspect_ratio'))}"></td>
      <td><input name="uf{i}_ctr" value="{vec('translation', '')}"></td>
      <td><input name="uf{i}_nrm" value="{vec('normal', '')}"></td>
      <td><input name="uf{i}_perm" value="{_g(uf.get('permeability'))}"></td>
      <td><input type="checkbox" name="uf{i}_del" title="remove row"></td>
    </tr>"""


class Panel:
    """Application state shared by request handlers."""

    def __init__(self, home: Path | None = None):
        self.config = Config(home)
        self.config.detect_dfnworks()
        self.config.detect_lagrit()
        self.cases_root = Path(self.config.home) / "cases"
        self.cases_root.mkdir(parents=True, exist_ok=True)
        self.db = Database(Path(self.config.home) / "panel.db")
        self.runner = JobRunner(self.config, self.db, self.cases_root)

    # ------------------------------------------------------------- helpers --
    def case_dir(self, case) -> Path:
        return self.cases_root / case["name"]

    def safe_relpath(self, case, rel: str) -> Path | None:
        base = self.case_dir(case).resolve()
        target = (base / rel).resolve()
        if target == base or base in target.parents:
            return target
        return None


class Handler(BaseHTTPRequestHandler):
    server: "PanelServer"

    @property
    def panel(self) -> Panel:
        return self.server.panel

    # ------------------------------------------------------------- plumbing --
    def log_message(self, fmt, *args):  # quiet access log
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8",
              extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, title: str, body: str, active: str = ""):
        self._send(code, R.layout(title, body, active).encode())

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise ValueError("upload too large")
        return self.rfile.read(length)

    def _form(self) -> dict:
        body = self._body().decode("utf-8", "replace")
        return {k: v[0] for k, v in
                urllib.parse.parse_qs(body, keep_blank_values=True).items()}

    def _files(self) -> list[tuple[str, str, bytes]]:
        """Parse multipart/form-data -> [(field, filename, data)]."""
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m:
            return []
        boundary = m.group(1).encode()
        body = self._body()
        out = []
        for part in body.split(b"--" + boundary):
            part = part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            if b"\r\n\r\n" not in part:
                continue
            head, data = part.split(b"\r\n\r\n", 1)
            headers = head.decode("utf-8", "replace")
            nm = re.search(r'name="([^"]*)"', headers)
            fn = re.search(r'filename="([^"]*)"', headers)
            name = nm.group(1) if nm else ""
            filename = fn.group(1) if fn else ""
            out.append((name, os.path.basename(filename), data))
        return out

    # -------------------------------------------------------------- routing --
    def do_GET(self):
        try:
            self._route_get()
        except Exception as exc:  # noqa: BLE001
            self._html(500, "Error", f"<div class='card error'><h2>Error</h2>"
                                     f"<pre>{R.esc(exc)}</pre></div>")

    def do_POST(self):
        try:
            self._route_post()
        except Exception as exc:  # noqa: BLE001
            self._html(500, "Error", f"<div class='card error'><h2>Error</h2>"
                                     f"<pre>{R.esc(exc)}</pre></div>")

    def _route_get(self):
        path = urllib.parse.urlparse(self.path).path
        query = dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.path).query))
        panel = self.panel

        if path in ("/", ""):
            return self.page_dashboard()
        if path == "/quick":
            return self.page_quick()
        if path == "/static/style.css":
            return self._static("static/style.css", "text/css")
        if path == "/static/app.js":
            return self._static("static/app.js",
                                "application/javascript")
        if path == "/case/new":
            return self.page_case_form(None)
        m = re.fullmatch(r"/case/(\d+)", path)
        if m:
            return self.page_case(int(m.group(1)))
        m = re.fullmatch(r"/case/(\d+)/file", path)
        if m:
            return self.file_view(int(m.group(1)), query)
        m = re.fullmatch(r"/case/(\d+)/edit", path)
        if m:
            return self.page_case_edit(int(m.group(1)), None)
        m = re.fullmatch(r"/case/(\d+)/download\.zip", path)
        if m:
            return self.download_zip(int(m.group(1)))
        m = re.fullmatch(r"/case/(\d+)/download/full_mesh", path)
        if m:
            return self.download_full_mesh(int(m.group(1)))
        m = re.fullmatch(r"/case/(\d+)/download/dfnworks", path)
        if m:
            return self.download_dfnworks(int(m.group(1)))
        m = re.fullmatch(r"/job/(\d+)", path)
        if m:
            return self.page_job(int(m.group(1)))
        if path == "/settings":
            return self.page_settings()
        if path == "/docs":
            return self.page_docs()
        if path == "/api/job":  # /api/job?id=3
            return self.api_job(int(query.get("id", 0)))
        if path == "/api/cases":
            return self.api_cases()
        self._html(404, "Not found", "<div class='card'><h2>404</h2></div>")

    def _route_post(self):
        path = urllib.parse.urlparse(self.path).path
        panel = self.panel
        if path == "/case/new":
            return self.action_case_new()
        if path == "/quick":
            return self.action_quick()
        m = re.fullmatch(r"/case/(\d+)/run", path)
        if m:
            form = self._form()
            case_id = int(m.group(1))
            stage = form.get("stage", "")
            if stage in (STAGE_DFN_MESH, STAGE_CONVERT, STAGE_GEOS_RUN):
                panel.runner.submit(case_id, stage)
            return self._redirect(f"/case/{case_id}")
        m = re.fullmatch(r"/case/(\d+)/params", path)
        if m:
            return self.action_case_params(int(m.group(1)))
        m = re.fullmatch(r"/case/(\d+)/upload", path)
        if m:
            return self.action_upload(int(m.group(1)))
        m = re.fullmatch(r"/case/(\d+)/delete", path)
        if m:
            case_id = int(m.group(1))
            case = panel.db.get_case(case_id)
            if case:
                shutil.rmtree(panel.case_dir(case), ignore_errors=True)
                panel.db.delete_case(case_id)
            return self._redirect("/")
        m = re.fullmatch(r"/case/(\d+)/file/delete", path)
        if m:
            form = self._form()
            case = panel.db.get_case(int(m.group(1)))
            target = panel.safe_relpath(case, form.get("path", ""))
            if case and target and target.is_file():
                target.unlink()
            return self._redirect(f"/case/{m.group(1)}")
        m = re.fullmatch(r"/job/(\d+)/cancel", path)
        if m:
            panel.runner.cancel(int(m.group(1)))
            return self._redirect(self.headers.get("Referer") or "/")
        if path == "/settings":
            form = self._form()
            for key in ("dfnworks_path", "lagrit_exe", "geos_exe",
                        "python_exe", "dfnworks_backend", "dfnworks_docker_image",
                        "geos_backend", "geos_docker_image"):
                panel.config[key] = form.get(key, "").strip()
            panel.config["use_compat_pythonpath"] = \
                1 if form.get("use_compat_pythonpath") else 0
            panel.config.save()
            return self._redirect("/settings")
        self._html(404, "Not found", "<div class='card'><h2>404</h2></div>")

    def _static(self, rel: str, ctype: str):
        p = PKG_DIR / rel
        if not p.exists():
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, p.read_bytes(), ctype,
                   {"Cache-Control": "max-age=60"})

    # ---------------------------------------------------------------- pages --
    def page_dashboard(self):
        panel = self.panel
        cases = panel.db.list_cases()
        jobs = panel.db.list_jobs(limit=8)
        rows = "".join(f"""<tr>
          <td><a href="/case/{c['id']}">{R.esc(c['name'])}</a></td>
          <td>{R.esc((c['description'] or '')[:80])}</td>
          <td>{R.fmt_ts(c['created_at'])}</td>
          <td>{len(panel.db.list_jobs(c['id']))}</td>
          <td class="actions"><form method="post" action="/case/{c['id']}/delete"
            onsubmit="return confirm('Delete case and all files?')">
            <button class="link-btn">delete</button></form></td>
        </tr>""" for c in cases)
        job_rows = "".join(R.job_row(j) for j in jobs)
        dw = panel.config["dfnworks_path"] or "(not configured)"
        lg = panel.config["lagrit_exe"] or "(not configured)"
        g_backend, g_image = panel.config.resolve_backend("geos")
        if g_backend == "docker" and g_image:
            geos = f"docker · {g_image}"
        elif g_backend == "native" and panel.config["geos_exe"]:
            geos = panel.config["geos_exe"]
        else:
            geos = "(not configured)"
        body = f"""
        <div class="cards">
          <div class="card"><h3>dfnWorks</h3><code>{R.esc(dw)}</code></div>
          <div class="card"><h3>LaGriT</h3><code>{R.esc(lg)}</code></div>
          <div class="card"><h3>GEOS</h3><code>{R.esc(geos)}</code></div>
        </div>
        <div class="card quick-cta">
          <div>
            <h2>Quick process</h2>
            <p class="muted">Upload one GEOS XML deck, a ZIP of dfnWorks
            files/outputs, or loose files and get the GEOS case back as a
            single ZIP — no configuration needed.</p>
          </div>
          <a class="btn primary" href="/quick">Upload &amp; process →</a>
        </div>
        <div class="row">
          <div class="card grow">
            <div class="card-head"><h2>Cases</h2>
              <a class="btn" href="/case/new">＋ New case</a></div>
            <table><thead><tr><th>Name</th><th>Description</th>
              <th>Created</th><th>Jobs</th><th></th></tr></thead>
              <tbody>{rows or '<tr><td colspan=5 class="empty">No cases yet — create one.</td></tr>'}</tbody></table>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h2>Recent jobs</h2></div>
          <table><thead><tr><th>#</th><th>Stage</th><th>Status</th>
            <th>Backend</th><th>Created</th><th>Duration</th><th></th></tr></thead>
            <tbody>{job_rows or '<tr><td colspan=7 class="empty">No jobs yet.</td></tr>'}</tbody></table>
        </div>"""
        self._html(200, "Dashboard", body)

    def page_case_form(self, _err=None):
        body = f"""
        <div class="card narrow">
        <h2>New case</h2>
        <form method="post" action="/case/new" class="stack">
          <label>Name<input name="name" required pattern="[A-Za-z0-9_\\-]+"
            title="letters, digits, _ and -"></label>
          <label>Description<input name="description"></label>
          <fieldset><legend>Domain & mesh</legend>
            <div class="grid3">
              <label>Domain X (m)<input name="dx" type="number" step="any" value="6"></label>
              <label>Domain Y (m)<input name="dy" type="number" step="any" value="6"></label>
              <label>Domain Z (m)<input name="dz" type="number" step="any" value="6"></label>
            </div>
            <div class="grid3">
              <label>Mesh h (m)<input name="h" type="number" step="any" value="0.35"></label>
              <label>Seed<input name="seed" type="number" value="42"></label>
              <label>Threads<input name="ncpu" type="number" value="4"></label>
            </div>
            <label class="chk"><input type="checkbox" name="mesh_dfm" checked>
              Also build conforming fracture–matrix DFM mesh (needed for the
              conformal GEOS path; requires LaGriT with Exodus)</label>
          </fieldset>
          <fieldset><legend>Fractures (optional — defaults to two intersecting
            rectangular fractures)</legend>
            <label>Stochastic families (JSON, optional)
              <textarea name="families" rows="4"
                placeholder='[{{"distribution":"constant","constant":2.0,"trend":0,"plunge":0,"probability":1.0}}]'></textarea></label>
            <label>User fractures (JSON, optional)
              <textarea name="fractures" rows="4"
                placeholder='[{{"radii":0.6,"translation":[-0.5,0,0],"normal":[0,0,1]}}]'></textarea></label>
          </fieldset>
          <button class="btn primary">Create case</button>
        </form></div>"""
        self._html(200, "New case", body)

    def page_case(self, case_id: int):
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._html(404, "Not found", "<div class='card'>No such case</div>")
        cdir = panel.case_dir(case)

        # file browser
        files = []
        if cdir.is_dir():
            for p in sorted(cdir.rglob("*")):
                if p.is_file() and "logs" not in p.relative_to(cdir).parts[:1] \
                        and p.name != "panel.db":
                    rel = p.relative_to(cdir).as_posix()
                    files.append((rel, p.stat().st_size))
                if len(files) > 400:
                    break
        rows = "".join(
            f"""<tr><td><a href="/case/{case_id}/file?path={urllib.parse.quote(rel)}&raw=0">{R.esc(rel)}</a></td>
            <td>{R.fmt_size(sz)}</td>
            <td class="actions">
              <a href="/case/{case_id}/file?path={urllib.parse.quote(rel)}&raw=1">raw</a>
              <form method="post" action="/case/{case_id}/file/delete"
                onsubmit="return confirm('Delete file?')">
                <input type="hidden" name="path" value="{R.esc(rel)}">
                <button class="link-btn">del</button></form></td></tr>"""
            for rel, sz in files)

        jobs = panel.db.list_jobs(case_id)
        job_rows = "".join(R.job_row(j) for j in jobs)

        art_rows = "".join(
            f"<tr><td>{R.esc(a['kind'])}</td>"
            f"<td><a href=\"/case/{case_id}/file?path={urllib.parse.quote(a['rel_path'])}\">{R.esc(a['rel_path'])}</a></td>"
            f"<td>{R.fmt_size(a['size'])}</td></tr>"
            for a in panel.db.list_artifacts(case_id))

        stage_buttons = "".join(
            R.stage_button(case_id, stage, label, sub)
            for stage, (label, sub) in _STAGE_LABELS.items())

        params = case["params"]
        net_html = PV.case_preview_html(cdir, params) or \
            PV.params_preview_html(params)
        body = f"""
        <div class="card-head">
          <h2>{R.esc(case['name'])}</h2>
          <span class="muted">{R.esc(case['description'] or '')}</span>
          <span class="btn-row">
            <a class="btn" href="/case/{case_id}/edit">✎ Edit DFN</a>
            <a class="btn" href="/case/{case_id}/download/full_mesh"
               title="The final dfnWorks surface mesh (full_mesh.inp)">⬇ Full mesh (.inp)</a>
            <a class="btn" href="/case/{case_id}/download/dfnworks"
               title="All dfnWorks stage outputs (mesh, uge, polys, dfm)">⬇ dfnWorks output (.zip)</a>
            <a class="btn primary" href="/case/{case_id}/download.zip">⬇ Results (.zip)</a>
          </span>
        </div>
        <div class="cards">
          <div class="card"><h3>Pipeline</h3><div class="stages">{stage_buttons}</div></div>
          <div class="card"><h3>Parameters</h3>
            <pre>{R.esc(json.dumps(params, indent=2))}</pre></div>
          <div class="card"><h3>Upload input files</h3>
            <form method="post" action="/case/{case_id}/upload"
                  enctype="multipart/form-data" class="stack">
              <label>Sub-directory (optional, e.g. <code>geos_case</code>)
                <input name="subdir" value=""></label>
              <input type="file" name="files" multiple>
              <button class="btn">Upload</button>
            </form>
            <p class="muted">A dfnGen input deck (<code>*.dat</code>) pre-fills
            the <a href="/case/{case_id}/edit">DFN editor</a>; a GEOS XML deck
            becomes the default for stage 3. Other files land in the case
            directory.</p>
          </div>
        </div>
        <div class="card"><div class="card-head"><h2>Fracture network preview</h2></div>
          {net_html}</div>
        <div class="card"><div class="card-head"><h2>Jobs</h2></div>
          <table><thead><tr><th>#</th><th>Stage</th><th>Status</th><th>Backend</th>
          <th>Created</th><th>Duration</th><th></th></tr></thead>
          <tbody>{job_rows or '<tr><td colspan=7 class="empty">No jobs yet.</td></tr>'}</tbody></table></div>
        <div class="card"><div class="card-head"><h2>Artifacts</h2></div>
          <table><thead><tr><th>Kind</th><th>Path</th><th>Size</th></tr></thead>
          <tbody>{art_rows or '<tr><td colspan=3 class="empty">None yet.</td></tr>'}</tbody></table></div>
        <div class="card"><div class="card-head"><h2>Files</h2></div>
          <table class="files"><thead><tr><th>Path</th><th>Size</th><th></th></tr></thead>
          <tbody>{rows or '<tr><td colspan=3 class="empty">Empty case.</td></tr>'}</tbody></table></div>
        """
        self._html(200, case["name"], body, active="")

    def page_job(self, job_id: int):
        panel = self.panel
        job = panel.db.get_job(job_id)
        if not job:
            return self._html(404, "Not found", "<div class='card'>No such job</div>")
        case = panel.db.get_case(job["case_id"])
        log = ""
        if job["log_path"] and Path(job["log_path"]).exists():
            log = Path(job["log_path"]).read_text(errors="replace")[-200000:]
        body = f"""
        <div class="card-head"><h2>Job #{job['id']} · {R.esc(job['stage'])}
          <span class="{R.STATUS_BADGE.get(job['status'],'badge')}">{R.esc(job['status'])}</span></h2>
          <a class="btn" href="/case/{case['id']}">← back to {R.esc(case['name'])}</a></div>
        <div class="card"><div class="card-head"><h3>Log</h3>
            <button class="btn copy-btn" data-copy-target="#logbox"
              title="Copy the whole log to the clipboard">⧉ Copy log</button></div>
          <pre class="log" id="logbox"
          data-job="{job['id']}" data-done="{0 if job['status'] in ('queued','running') else 1}">{R.esc(log) or '(no output yet)'}</pre></div>
        <div class="card"><h3>Details</h3><pre>{R.esc(json.dumps(job['details'], indent=2))}</pre></div>
        """
        self._html(200, f"Job #{job_id}", body)

    def page_quick(self):
        panel = self.panel
        geos_ok = panel.config.geos_ready()
        if not geos_ok:
            geos_note = "no (stage 3 will be skipped — set it up in Settings)"
        else:
            backend, image = panel.config.resolve_backend("geos")
            if backend == "docker":
                geos_note = ("yes (docker image <code>%s</code>)"
                             % R.esc(image))
            else:
                geos_note = ("yes (native binary <code>%s</code>)"
                             % R.esc(panel.config["geos_exe"]))
        body = f"""
        <div class="card narrow">
        <h2>Quick process</h2>
        <p class="muted">Drop a <b>ZIP</b> of your dfnWorks files, a single
        <b>GEOS XML deck</b>, or individual files and press <b>Process</b>.
        The panel inspects the contents and runs the right stage(s)
        automatically, then lets you download the results as one ZIP.</p>
        <form method="post" action="/quick" enctype="multipart/form-data" class="stack">
          <label>Name (optional — derived from the file name otherwise)
            <input name="name" placeholder="my_network"></label>
          <label>ZIP, one XML deck, or loose files
            <input type="file" name="files" multiple required></label>
          <label>What to do
            <select name="action">
              <option value="auto" selected>Auto-detect (recommended)</option>
              <option value="full">Run full pipeline (dfnWorks → convert → GEOS)</option>
              <option value="convert">Convert only (dfnWorks outputs → GEOS case)</option>
              <option value="geos">Run GEOS only (one XML deck, + mesh if it needs one)</option>
            </select></label>
          <p class="muted">A single XML is enough when the deck is
             self-contained — the EDFM deck (<code>geos_dfn_edfm.xml</code>)
             builds its own matrix mesh, so it needs no other files. Decks that
             point at a mesh (<code>.vtm</code>/<code>.vtu</code>) or at data
             tables (<code>.txt</code>) need those files uploaded with them.</p>
          <p class="muted">Recognised: <code>full_mesh.inp</code>,
             <code>params.txt</code>, <code>polys/</code>,
             <code>dfm_mesh/dfm_tet_mesh.inp</code>, <code>dfn_driver.py</code>,
             GEOS <code>*.xml</code>/<code>*.vtm</code>/<code>*.vtu</code>.
             GEOS solver: <b>{geos_note}</b>.</p>
          <button class="btn primary">Process</button>
        </form>
        <p class="muted">Prefer manual control? Use <a href="/case/new">New case</a>
        and run the three stages yourself.</p>
        </div>"""
        self._html(200, "Quick process", body, active="quick")

    def action_quick(self):
        """Upload → create case → auto-run detected pipeline."""
        import time as _time

        from . import ingest
        panel = self.panel
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._redirect("/quick")
        boundary_m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not boundary_m:
            return self._redirect("/quick")
        boundary = boundary_m.group(1).encode()
        body = self._body()

        # split parts
        files, name_field, action_field = [], "", "auto"
        for part in body.split(b"--" + boundary):
            part = part.strip(b"\r\n")
            if not part or part == b"--" or b"\r\n\r\n" not in part:
                continue
            head, data = part.split(b"\r\n\r\n", 1)
            headers = head.decode("utf-8", "replace")
            fn = re.search(r'filename="([^"]*)"', headers)
            if fn and fn.group(1):
                files.append((os.path.basename(
                    fn.group(1).replace("\\", "/")), data))
            elif 'name="name"' in headers:
                name_field = data.decode("utf-8", "replace").strip()
            elif 'name="action"' in headers:
                action_field = data.decode("utf-8", "replace").strip() or "auto"
        if not files:
            return self._redirect("/quick")

        # case name: field, zip stem, or timestamp
        raw_name = name_field or os.path.splitext(files[0][0])[0] or \
            f"case_{int(_time.time())}"
        name = re.sub(r"[^A-Za-z0-9_\-]", "_", raw_name)[:60] or \
            f"case_{int(_time.time())}"
        existing = {c["name"] for c in panel.db.list_cases()}
        base, n = name, 2
        while name in existing:
            name = f"{base}-{n}"
            n += 1

        case_id = panel.db.create_case(name, "created by Quick process",
                                       {"source": "quick",
                                        "action": action_field})
        case_dir = panel.case_dir(panel.db.get_case(case_id))
        case_dir.mkdir(parents=True, exist_ok=True)

        # extract zips / place files
        written: list[str] = []
        loose = []
        for filename, data in files:
            if filename.lower().endswith(".zip"):
                try:
                    written += ingest.safe_extract_zip(data, case_dir)
                except Exception as exc:  # noqa: BLE001
                    (case_dir / "extract_error.txt").write_text(str(exc))
            else:
                loose.append(("files", filename, data))
        if loose:
            written += ingest.place_loose_files(loose, case_dir)

        for rel in written:
            p = case_dir / rel
            panel.db.add_artifact(case_id, "input", rel,
                                  p.stat().st_size if p.is_file() else 0)

        # decide pipeline
        geos_ok = panel.config.geos_ready()
        info = ingest.detect_action(written, geos_ok, case_dir)
        action = action_field if action_field != "auto" else info["action"]
        chain_map = {
            "full": ["dfn_mesh", "convert_to_geos"]
                    + (["run_geos"] if geos_ok else []),
            "convert": ["convert_to_geos"],
            "geos": ["run_geos"],
        }
        chain = chain_map.get(action, info["chain"])
        params = {"source": "quick", "action": action, "detected": info,
                  "files": written[:50]}
        if info.get("deck"):
            params["deck"] = info["deck"]
        # persist first: the job thread reads the case row as soon as it starts
        panel.db.update_case(case_id, params=params)
        if chain:
            panel.runner.submit(case_id, chain[0],
                                details={"quick": True,
                                         "detected": info,
                                         "action": action},
                                chain=chain[1:])
        self._redirect(f"/case/{case_id}")

    def download_zip(self, case_id: int):
        """Bundle the case outputs into a downloadable ZIP."""
        import io as _io
        import zipfile as _zipfile
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._html(404, "Not found", "<div class='card'>No such case</div>")
        case_dir = panel.case_dir(case)
        skip_dirs = set()
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED,
                              compresslevel=6) as zf:
            for p in sorted(case_dir.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(case_dir)
                parts = rel.parts
                if parts and parts[0] in ("logs",) and len(parts) > 1:
                    continue
                if p.name in (".dfnworksrc",) or p.suffix == ".lg":
                    continue
                if parts and parts[0] in skip_dirs:
                    continue
                zf.write(p, arcname=str(rel))
        data = buf.getvalue()
        self._send(200, data, "application/zip", {
            "Content-Disposition":
                f'attachment; filename="{case["name"]}_results.zip"'})

    def _friendly_missing(self, case_id: int, title: str, hint: str) -> None:
        body = f"""
        <div class="card-head"><h2>{R.esc(title)}</h2>
          <a class="btn" href="/case/{case_id}">← back to case</a></div>
        <div class="card"><p>{hint}</p></div>"""
        self._html(404, title, body)

    def download_full_mesh(self, case_id: int):
        """Download just the final dfnWorks surface mesh (full_mesh.inp)."""
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._html(404, "Not found",
                              "<div class='card'>No such case</div>")
        target = ingest.find_full_mesh(panel.case_dir(case))
        if not target:
            return self._friendly_missing(
                case_id, "No full mesh yet",
                "This case has no <code>full_mesh.inp</code> yet. Run the "
                "<b>1 · dfnWorks mesh</b> stage (or upload dfnWorks outputs), "
                "then this button downloads the final surface mesh on its own.")
        self._send(200, target.read_bytes(), "application/octet-stream", {
            "Content-Disposition":
                f'attachment; filename="{case["name"]}_full_mesh.inp"'})

    def download_dfnworks(self, case_id: int):
        """Download all dfnWorks stage outputs (the output/ folder) as a ZIP."""
        import io as _io
        import zipfile as _zipfile
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._html(404, "Not found",
                              "<div class='card'>No such case</div>")
        files = ingest.dfnworks_output_files(panel.case_dir(case))
        if not files:
            return self._friendly_missing(
                case_id, "No dfnWorks outputs yet",
                "Nothing from dfnWorks was found in this case. Run the "
                "<b>1 · dfnWorks mesh</b> stage first — then this button "
                "bundles the whole <code>output/</code> folder (mesh "
                "<code>.inp/.uge</code>, <code>polys/</code>, "
                "<code>params.txt</code>, the DFM mesh, …) as one ZIP, "
                "separate from the full results.")
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED,
                              compresslevel=6) as zf:
            for path, arc in files:
                zf.write(path, arcname=arc)
        self._send(200, buf.getvalue(), "application/zip", {
            "Content-Disposition":
                f'attachment; filename="{case["name"]}_dfnworks_output.zip"'})

    # ------------------------------------------------------------- DFN edit --
    def page_case_edit(self, case_id: int, draft: dict | None = None,
                       error: str = "", notice: str = "") -> None:
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._html(404, "Not found",
                              "<div class='card'>No such case</div>")
        params = draft if draft is not None else dict(case.get("params") or {})
        families = list(params.get("families") or [])
        fractures = list(params.get("fractures") or [])
        if draft is None and not families and not fractures:
            # nothing defined yet — show the driver's default layout to edit
            families = [dict(f) for f in DEFAULT_FAMILIES]
        fam_rows = "".join(_family_row_html(i, f)
                           for i, f in enumerate(families))
        uf_rows = "".join(_uf_row_html(i, f)
                          for i, f in enumerate(fractures))
        domain = [float(v) for v in (params.get("domain") or [6.0] * 3)]
        bf = params.get("boundary_faces") or [1, 1, 0, 0, 0, 0]
        bf_val = ",".join(str(int(v)) for v in bf)
        n_poly = int(params.get("n_poly") or 0)
        unmapped = params.get("dfn_unmapped") or {}
        notes = params.get("dfn_notes") or []
        notes_html = "".join(f"<p class='muted'>ℹ {R.esc(n)}</p>" for n in notes)
        unmapped_html = ""
        if unmapped:
            rows = "".join(f"<tr><td><code>{R.esc(k)}</code></td>"
                           f"<td><code>{R.esc(v)}</code></td></tr>"
                           for k, v in unmapped.items())
            src = params.get("dfn_source")
            src_note = f" (from <code>{R.esc(src)}</code>)" if src else ""
            unmapped_html = f"""
            <div class="card"><h3>Other dfnGen keys read from the uploaded
              deck{src_note}</h3>
              <p class="muted">These are kept verbatim for reference; the panel
              does not edit them.</p>
              <table><thead><tr><th>Key</th><th>Value</th></tr></thead>
              <tbody>{rows}</tbody></table></div>"""
        net_html = PV.params_preview_html(params)
        err_html = f"<div class='card error'>{error}</div>" if error else ""
        ok_html = f"<div class='card ok-card'>{notice}</div>" if notice else ""
        body = f"""
        <div class="card-head"><h2>Edit DFN — {R.esc(case['name'])}</h2>
          <span class="btn-row"><a class="btn" href="/case/{case_id}">← back
            to case</a></span></div>
        {err_html}{ok_html}
        <form method="post" action="/case/{case_id}/params" class="stack">
          <input type="hidden" name="fam_count" value="{len(families)}">
          <input type="hidden" name="uf_count" value="{len(fractures)}">
          <fieldset><legend>Domain & mesh</legend>
            <div class="grid3">
              <label>Domain X (m)<input name="dx" type="number" step="any"
                value="{_g(domain[0])}"></label>
              <label>Domain Y (m)<input name="dy" type="number" step="any"
                value="{_g(domain[1])}"></label>
              <label>Domain Z (m)<input name="dz" type="number" step="any"
                value="{_g(domain[2])}"></label>
            </div>
            <div class="grid3">
              <label>Mesh h (m)<input name="h" type="number" step="any"
                value="{_g(params.get('h', 0.35))}"></label>
              <label>Seed<input name="seed" type="number"
                value="{int(params.get('seed', 42))}"></label>
              <label>Threads<input name="ncpu" type="number"
                value="{int(params.get('ncpu', 4))}"></label>
            </div>
            <label class="chk"><input type="checkbox" name="mesh_dfm"
              {"checked" if params.get("mesh_dfm", True) else ""}>
              Also build the conforming fracture–matrix DFM mesh (needed for
              the conformal GEOS path)</label>
          </fieldset>
          <fieldset><legend>Fracture count & boundaries</legend>
            <div class="grid3">
              <label>Number of fractures (nPoly)
                <input name="n_poly" type="number" min="1"
                  value="{n_poly}"></label>
              <label>Boundary faces (x−, x+, y−, y+, z−, z+)
                <input name="boundary_faces" value="{bf_val}"></label>
              <label class="chk"><input type="checkbox"
                name="ignore_boundary_faces"
                {"checked" if params.get("ignore_boundary_faces") else ""}>
                Keep every cluster of intersecting fractures even if it
                touches none of the flagged boundary faces (dfnGen
                <code>ignoreBoundaryFaces</code>; recommended for small
                networks)</label>
            </div>
            <p class="muted"><b>nPoly</b> = the total number of fractures
            dfnGen accepts before it stops (user fractures included; leave
            blank for the default of 24). This is the direct way to control
            <i>how many</i> fractures the network has.</p>
          </fieldset>
          <fieldset><legend>Stochastic families</legend>
            <div class="tbl-scroll"><table class="edit-grid">
              <thead><tr><th>Shape</th><th>Distribution</th><th>Size</th>
                <th title="log std (log_normal only)">Log SD</th><th>Min</th>
                <th>Max</th><th>Aspect</th><th>Prob</th><th>Trend°</th>
                <th>Plunge°</th><th title="Fisher kappa">Kappa</th>
                <th title="constant beta rotation">β const</th><th title="beta angle">β°</th>
                <th title="remove row">✕</th></tr></thead>
              <tbody>{fam_rows}</tbody></table></div>
            <p class="muted">{_FAMILY_DIST_HELP}</p>
            <span><button class="btn" name="add_family" value="1">＋ Add
              family</button></span>
          </fieldset>
          <fieldset><legend>User-defined fractures (exact placement)</legend>
            <div class="tbl-scroll"><table class="edit-grid">
              <thead><tr><th>Shape</th><th>Radius<br>(half size, m)</th>
                <th>Aspect</th><th>Center x,y,z (m)</th>
                <th>Normal x,y,z</th><th>Permeability</th>
                <th title="remove row">✕</th></tr></thead>
              <tbody>{uf_rows}</tbody></table></div>
            <p class="muted">These fractures are inserted exactly as given
            (dfnGen/FRAM still rejects intersections shorter than
            <code>h</code> — keep margins larger than the mesh resolution).</p>
            <span><button class="btn" name="add_fracture" value="1">＋ Add
              fracture</button></span>
          </fieldset>
          <fieldset><legend>Network preview (from these parameters)</legend>
            {net_html}
          </fieldset>
          <div class="btn-row">
            <button class="btn primary" name="action" value="save">💾 Save</button>
            <button class="btn" name="action" value="save_run">💾 Save &
              run mesh</button>
            <button class="btn" name="action" value="reset"
              onclick="return confirm('Reset the DFN configuration to defaults? Current settings (including imported .dat values) will be replaced.')">↺
              Reset to defaults</button>
          </div>
        </form>
        {unmapped_html}{notes_html}
        """
        self._html(200, f"Edit DFN · {case['name']}", body)

    def action_case_params(self, case_id: int):
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._redirect("/")
        form = self._form()
        if form.get("action") == "reset":
            panel.db.update_case(case_id, params=default_params())
            return self.page_case_edit(
                case_id, None,
                notice="<b>Reset to default DFN configuration.</b> Domain, "
                       "mesh, families and the fracture count are back to "
                       "the standard setup.")
        params, errors = _params_from_form(form, case.get("params") or {})
        err_html = "<br>".join(errors)
        if "add_family" in form:
            draft = dict(params)
            draft["families"] = list(params.get("families") or []) + \
                [dict(_BLANK_FAMILY)]
            return self.page_case_edit(case_id, draft, error=err_html)
        if "add_fracture" in form:
            draft = dict(params)
            draft["fractures"] = list(params.get("fractures") or []) + \
                [{}]
            return self.page_case_edit(case_id, draft, error=err_html)
        if errors:
            return self.page_case_edit(case_id, params, error=err_html)
        panel.db.update_case(case_id, params=params)
        if form.get("action") == "save_run":
            panel.runner.submit(case_id, STAGE_DFN_MESH)
            return self._redirect(f"/case/{case_id}")
        return self.page_case_edit(
            case_id, None,
            notice="<b>Saved.</b> The dfnWorks driver is regenerated from "
                   "these parameters when the mesh stage runs.")

    def page_settings(self):
        panel = self.panel
        c = panel.config
        fields = [
            ("dfnworks_path", "dfnWorks repository", c["dfnworks_path"]),
            ("lagrit_exe", "LaGriT executable", c["lagrit_exe"]),
            ("geos_exe", "GEOS executable (native backend only; blank = docker)",
             c["geos_exe"]),
            ("python_exe", "Python for dfnWorks (blank = panel python)",
             c["python_exe"]),
            ("dfnworks_backend", "dfnWorks backend (auto|native|docker)",
             c["dfnworks_backend"]),
            ("dfnworks_docker_image", "dfnWorks docker image",
             c["dfnworks_docker_image"]),
            ("geos_backend", "GEOS backend (auto|native|docker)", c["geos_backend"]),
            ("geos_docker_image",
             "GEOS docker image (blank = auto-detect dfn-geos:1.1)",
             c["geos_docker_image"]),
        ]
        inputs = "".join(
            f"<label>{R.esc(label)}"
            f"<input name=\"{name}\" value=\"{R.esc(value)}\"></label>"
            for name, label, value in fields)
        backend, image = c.resolve_backend("geos")
        detected = c.detect_geos_image()
        if backend == "docker" and image:
            solver = (f"✅ docker image <code>{R.esc(image)}</code> "
                      "(binary <code>/opt/geos/bin/geosx</code> inside it)")
            if not c["geos_docker_image"]:
                solver += (" — detected locally; you can leave the image field "
                           "blank.")
        elif backend == "native" and c["geos_exe"]:
            solver = f"✅ native binary <code>{R.esc(c['geos_exe'])}</code>"
        else:
            solver = ("<span class=\"warn\">⚠ not configured — stage 3 (Run GEOS) "
                      "will refuse.</span>")
            if detected:
                solver += (f" A GEOS image (<code>{R.esc(detected)}</code>) "
                           "exists; set 'GEOS backend' to docker to use it.")
        body = f"""
        <div class="card narrow"><h2>Settings</h2>
        <form method="post" action="/settings" class="stack">
          {inputs}
          <label class="chk"><input type="checkbox" name="use_compat_pythonpath"
            {"checked" if c["use_compat_pythonpath"] else ""}>
            Prepend workbench <code>compat/</code> + <code>vendor/</code> to
            PYTHONPATH so pydfnworks runs without pandas/pyvtk/h5py/fpdf
            (recommended; disable if your env has full dependencies)</label>
          <button class="btn primary">Save</button>
        </form>
        <p class="muted"><strong>GEOS solver:</strong> {solver}</p>
        <p class="muted">Settings are stored in <code>{R.esc(c.path)}</code>.</p></div>
        """
        self._html(200, "Settings", body, active="settings")

    def page_docs(self):
        body = f"""
        <div class="card"><h2>Workflow guide</h2>
        <ol>
          <li><b>Create a case</b> — defines the domain, mesh resolution
              (<code>h</code>) and the fracture network (user-defined or
              stochastic families).</li>
          <li><b>Edit the DFN (✎ Edit DFN)</b> — any time before meshing:
              change the model dimensions, the <b>number of fractures</b>
              (nPoly), or the family/user-fracture tables. Upload a dfnGen
              <code>.dat</code> deck on the case page to pre-fill the editor
              from an existing model. The page shows an SVG preview of the
              network (XY/XZ/YZ) from the current parameters, and the real
              generated polygons after a mesh run.</li>
          <li><b>Run “dfnWorks mesh”</b> — runs dfnGen + LaGriT
              (<code>full_mesh.inp/uge</code>, and optionally the conforming
              DFM mesh with fracture facets).</li>
          <li><b>Download the dfnWorks results</b> — from the case header:
              <i>⬇ Full mesh (.inp)</i> for just the surface mesh,
              <i>⬇ dfnWorks output (.zip)</i> for every dfnWorks artifact
              (the whole <code>output/</code> folder), and
              <i>⬇ Results (.zip)</i> for the whole case.</li>
          <li><b>Run “Convert → GEOS”</b> — produces a VTK multi-block case
              (<code>main.vtu</code> matrix + <code>fracture.vtu</code> face
              block with <code>collocated_nodes</code>) and two ready-to-run
              GEOS decks:
              <ul>
                <li><code>geos_dfn_fractures.xml</code> — conformal fracture
                    flow (Option B),</li>
                <li><code>geos_dfn_edfm.xml</code> — EDFM reconstruction
                    (Option C).</li>
              </ul></li>
          <li><b>Run “Run GEOS”</b> — executes GEOS on the converted case
              (configure the GEOS executable in Settings).</li>
        </ol>
        <p>See <code>report/feasibility_report.md</code> in the workbench for
        the full Task-1 feasibility study.</p></div>
        """
        self._html(200, "Guide", body, active="docs")

    # --------------------------------------------------------------- actions --
    def action_case_new(self):
        panel = self.panel
        form = self._form()
        name = form.get("name", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            return self.page_case_form()
        params = default_params()
        params["domain"] = [float(form.get("dx", 6) or 6),
                            float(form.get("dy", 6) or 6),
                            float(form.get("dz", 6) or 6)]
        params["h"] = float(form.get("h", 0.35) or 0.35)
        params["seed"] = int(form.get("seed", 42) or 42)
        params["ncpu"] = int(form.get("ncpu", 4) or 4)
        params["mesh_dfm"] = bool(form.get("mesh_dfm"))
        for key in ("families", "fractures"):
            raw = (form.get(key) or "").strip()
            if raw:
                try:
                    params[key] = json.loads(raw)
                except ValueError:
                    pass
        case_id = panel.db.create_case(name, form.get("description", ""),
                                       params)
        panel.case_dir(panel.db.get_case(case_id)).mkdir(parents=True,
                                                         exist_ok=True)
        self._redirect(f"/case/{case_id}")

    def action_upload(self, case_id: int):
        panel = self.panel
        case = panel.db.get_case(case_id)
        if not case:
            return self._redirect("/")
        import re as _re
        head = self.headers.get("Content-Type", "")
        m = _re.search(r'boundary="?([^";]+)"?', head)
        if not m:
            return self._redirect(f"/case/{case_id}")
        boundary = m.group(1).encode()
        body = self._body()
        saved = 0
        uploaded: list[str] = []
        for part in body.split(b"--" + boundary):
            part = part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            if b"\r\n\r\n" not in part:
                continue
            head_part, data = part.split(b"\r\n\r\n", 1)
            headers = head_part.decode("utf-8", "replace")
            if 'name="subdir"' in headers:
                self._pending_subdir = data.decode("utf-8", "replace").strip()
                continue
            fn = _re.search(r'filename="([^"]*)"', headers)
            if not fn or not fn.group(1):
                continue
            filename = os.path.basename(fn.group(1).replace("\\", "/"))
            target_dir = panel.case_dir(case)
            rel = filename
            sub_m = None
            # look ahead: subdir field part appears before files in the form
            if self._pending_subdir:
                sub = self._pending_subdir
                if sub:
                    target_dir = panel.case_dir(case) / sub
                    rel = f"{sub}/{filename}"
                self._pending_subdir = ""
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / filename).write_bytes(data)
            panel.db.add_artifact(case_id, "input", rel, len(data))
            uploaded.append(rel)
            saved += 1
        # a dfnGen input deck (*.dat) pre-fills the DFN editor
        if uploaded:
            case_dir = panel.case_dir(case)
            for rel in uploaded:
                p = case_dir / rel
                if p.suffix.lower() != ".dat" or not p.is_file():
                    continue
                try:
                    parsed = dfn_input.parse_dfn_dat(p.read_text(errors="replace"))
                except Exception:  # noqa: BLE001 — never block an upload
                    continue
                if not dfn_input.looks_like_dfn_dat(parsed):
                    continue
                params = dict(case.get("params") or {})
                params.update(parsed["params"])
                if parsed["families"]:
                    params["families"] = parsed["families"]
                params["dfn_unmapped"] = parsed["unmapped"]
                params["dfn_notes"] = parsed["notes"]
                params["dfn_source"] = rel
                panel.db.update_case(case_id, params=params)
                return self._redirect(f"/case/{case_id}/edit")
            # a GEOS XML deck uploaded by hand becomes the stage-3 default
            deck = ingest.pick_deck(uploaded, case_dir)
            if deck and ingest.is_runnable_deck(case_dir / deck):
                params = dict(case.get("params") or {})
                params["deck"] = deck
                panel.db.update_case(case_id, params=params)
        self._redirect(f"/case/{case_id}")

    _pending_subdir = ""

    def file_view(self, case_id: int, query: dict):
        panel = self.panel
        case = panel.db.get_case(case_id)
        target = panel.safe_relpath(case, query.get("path", ""))
        if not target or not target.is_file():
            return self._html(404, "Not found", "<div class='card'>No such file</div>")
        if query.get("raw") == "1" or (target.suffix.lower() not in TEXT_EXTS
                                       and target.suffix.lower() not in MESH_EXTS):
            ctype = "application/octet-stream"
            data = target.read_bytes()
            self._send(200, data, ctype, {
                "Content-Disposition":
                    f'attachment; filename="{target.name}"'})
            return
        text = target.read_text(errors="replace")
        if len(text) > 400_000:
            text = text[:400_000] + "\n... (truncated preview)"
        if target.suffix.lower() in MESH_EXTS:
            hint = ""
            if target.suffix.lower() == ".pvd":
                hint = ("This is a <b>time-series index</b> — it only lists the "
                        "time steps. It contains no geometry: to see the mesh "
                        "and the results, open it with ParaView (File → Open → "
                        "Apply), keeping the neighbouring folder next to it.")
            elif target.suffix.lower() == ".vtm":
                hint = ("This is a <b>multi-block mesh</b> (blocks → "
                        "individual <code>.vtu</code> files). Open it with "
                        "ParaView to see the geometry.")
            else:
                hint = ("This is a <b>3-D mesh/result file</b>. The text below "
                        "is the raw data — open the file with ParaView "
                        "(or VisIt) to see it.")
            body = f"""
        <div class="card-head"><h2><code>{R.esc(query.get('path'))}</code></h2>
          <a class="btn" href="/case/{case_id}">← back</a></div>
        <div class="card">
          <p><b>Not a picture.</b> {hint}</p>
          <p>ParaView (free): <a href="https://www.paraview.org/download/"
             target="_blank" rel="noopener">paraview.org/download</a> —
             install, then <i>File → Open</i> this file and click <i>Apply</i>.
             Colour by <code>pressure</code>; use the time slider to animate.
             More: <code>docs/USER_GUIDE.md</code> §10.</p>
          <p><a class="btn" href="/case/{case_id}/file?raw=1&amp;path=
             {R.esc(query.get('path'))}">⬇ download this file</a></p>
          <details><summary>show raw contents (first 200 lines)</summary>
            <button class="btn copy-btn" data-copy-target="#rawpre">⧉ Copy</button>
            <pre class="log" id="rawpre">{R.esc(chr(10).join(text.splitlines()[:200]))}</pre>
          </details>
        </div>"""
            return self._html(200, target.name, body)
        body = f"""
        <div class="card-head"><h2><code>{R.esc(query.get('path'))}</code></h2>
          <a class="btn" href="/case/{case_id}">← back</a></div>
        <div class="card"><div class="card-head"><h3>Contents</h3>
          <button class="btn copy-btn" data-copy-target="#filetext"
            title="Copy the file contents to the clipboard">⧉ Copy file</button></div>
          <pre class="log" id="filetext">{R.esc(text)}</pre></div>"""
        self._html(200, target.name, body)

    # ----------------------------------------------------------------- APIs --
    def api_job(self, job_id: int):
        import json as _json
        job = self.panel.db.get_job(job_id)
        if not job:
            return self._send(404, b'{"error":"no such job"}',
                              "application/json")
        log = ""
        if job["log_path"] and Path(job["log_path"]).exists():
            log = Path(job["log_path"]).read_text(errors="replace")[-200000:]
        self._send(200, _json.dumps({"job": {k: job[k] for k in
                                             ("id", "status", "stage",
                                              "returncode", "details")},
                                     "log": log}).encode(),
                   "application/json")

    def api_cases(self):
        import json as _json
        self._send(200, _json.dumps(self.panel.db.list_cases()).encode(),
                   "application/json")


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, panel: Panel):
        super().__init__(addr, Handler)
        self.panel = panel


def serve(port: int = 8765, home: Path | None = None) -> None:
    panel = Panel(home)
    try:
        httpd = PanelServer(("0.0.0.0", port), panel)
    except OSError as exc:
        print(f"cannot listen on port {port}: {exc}", flush=True)
        print(f"another program is already using it — try:", flush=True)
        print(f"    python run_panel.py --port {port + 1}", flush=True)
        raise SystemExit(1)
    print(f"dfn-GEOS Workbench panel → http://localhost:{port}")
    print(f"  settings: {panel.config.path}")
    print(f"  cases:    {panel.cases_root}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
