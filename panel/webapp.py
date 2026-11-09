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
from .jobs import (STAGE_CONVERT, STAGE_DFN_MESH, STAGE_GEOS_RUN, JobRunner)

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
        m = re.fullmatch(r"/case/(\d+)/download\.zip", path)
        if m:
            return self.download_zip(int(m.group(1)))
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
        geos = panel.config["geos_exe"] or "(not configured)"
        body = f"""
        <div class="cards">
          <div class="card"><h3>dfnWorks</h3><code>{R.esc(dw)}</code></div>
          <div class="card"><h3>LaGriT</h3><code>{R.esc(lg)}</code></div>
          <div class="card"><h3>GEOS</h3><code>{R.esc(geos)}</code></div>
        </div>
        <div class="card quick-cta">
          <div>
            <h2>Quick process</h2>
            <p class="muted">Upload a ZIP of dfnWorks files (or outputs) and get
            the GEOS case back as a single ZIP — no configuration needed.</p>
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
        body = f"""
        <div class="card-head">
          <h2>{R.esc(case['name'])}</h2>
          <span class="muted">{R.esc(case['description'] or '')}</span>
          <span><a class="btn primary"
            href="/case/{case_id}/download.zip">⬇ Download results (.zip)</a></span>
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
            <p class="muted">Uploaded files land in the case directory and can be
            referenced by generated decks (e.g. GEOS XML or dfnWorks inputs).</p>
          </div>
        </div>
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
        <div class="card"><pre class="log" id="logbox"
          data-job="{job['id']}" data-done="{0 if job['status'] in ('queued','running') else 1}">{R.esc(log) or '(no output yet)'}</pre></div>
        <div class="card"><h3>Details</h3><pre>{R.esc(json.dumps(job['details'], indent=2))}</pre></div>
        """
        self._html(200, f"Job #{job_id}", body)

    def page_quick(self):
        panel = self.panel
        geos_ok = bool(panel.config["geos_exe"])
        body = f"""
        <div class="card narrow">
        <h2>Quick process</h2>
        <p class="muted">Drop a <b>ZIP</b> of your dfnWorks files (or the raw
        output files) and press <b>Process</b>. The panel inspects the contents
        and runs the right stage(s) automatically, then lets you download the
        results as one ZIP.</p>
        <form method="post" action="/quick" enctype="multipart/form-data" class="stack">
          <label>Name (optional — derived from the file name otherwise)
            <input name="name" placeholder="my_network"></label>
          <label>ZIP file or loose files
            <input type="file" name="files" multiple required></label>
          <label>What to do
            <select name="action">
              <option value="auto" selected>Auto-detect (recommended)</option>
              <option value="full">Run full pipeline (dfnWorks → convert → GEOS)</option>
              <option value="convert">Convert only (dfnWorks outputs → GEOS case)</option>
              <option value="geos">Run GEOS only (XML + mesh uploaded)</option>
            </select></label>
          <p class="muted">Recognised: <code>full_mesh.inp</code>,
             <code>params.txt</code>, <code>polys/</code>,
             <code>dfm_mesh/dfm_tet_mesh.inp</code>, <code>dfn_driver.py</code>,
             GEOS <code>*.xml</code>/<code>*.vtm</code>/<code>*.vtu</code>.
             GEOS executable configured: <b>{"yes" if geos_ok else "no"}</b>{"" if geos_ok else " (stage 3 will be skipped)"}.</p>
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
        info = ingest.detect_action(written, bool(panel.config["geos_exe"]))
        action = action_field if action_field != "auto" else info["action"]
        chain_map = {
            "full": ["dfn_mesh", "convert_to_geos"]
                    + (["run_geos"] if panel.config["geos_exe"] else []),
            "convert": ["convert_to_geos"],
            "geos": ["run_geos"],
        }
        chain = chain_map.get(action, info["chain"])
        if chain:
            panel.runner.submit(case_id, chain[0],
                                details={"quick": True,
                                         "detected": info,
                                         "action": action},
                                chain=chain[1:])
        panel.db.update_case(case_id, params={
            "source": "quick", "action": action, "detected": info,
            "files": written[:50]})
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

    def page_settings(self):
        panel = self.panel
        c = panel.config
        fields = [
            ("dfnworks_path", "dfnWorks repository", c["dfnworks_path"]),
            ("lagrit_exe", "LaGriT executable", c["lagrit_exe"]),
            ("geos_exe", "GEOS executable", c["geos_exe"]),
            ("python_exe", "Python for dfnWorks (blank = panel python)",
             c["python_exe"]),
            ("dfnworks_backend", "dfnWorks backend (auto|native|docker)",
             c["dfnworks_backend"]),
            ("dfnworks_docker_image", "dfnWorks docker image",
             c["dfnworks_docker_image"]),
            ("geos_backend", "GEOS backend (auto|native|docker)", c["geos_backend"]),
            ("geos_docker_image", "GEOS docker image (optional)",
             c["geos_docker_image"]),
        ]
        inputs = "".join(
            f"<label>{R.esc(label)}"
            f"<input name=\"{name}\" value=\"{R.esc(value)}\"></label>"
            for name, label, value in fields)
        backend, image = c.resolve_backend("geos")
        if backend == "docker" and not image:
            solver = ("<span class=\"warn\">⚠ not configured — stage 3 (Run GEOS) "
                      "will refuse. Set a GEOS docker image, or ignore it if you "
                      "only need the mesh and the decks.</span>")
        elif backend == "docker":
            solver = (f"✅ docker image <code>{R.esc(image)}</code> "
                      "(binary <code>/opt/geos/bin/geosx</code> inside it)")
        elif c["geos_exe"]:
            solver = f"✅ native binary <code>{R.esc(c['geos_exe'])}</code>"
        else:
            solver = ("<span class=\"warn\">⚠ not configured — stage 3 (Run GEOS) "
                      "will refuse.</span>")
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
          <li><b>Run “dfnWorks mesh”</b> — runs dfnGen + LaGriT
              (<code>full_mesh.inp/uge</code>, and optionally the conforming
              DFM mesh with fracture facets).</li>
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
        params = {
            "domain": [float(form.get("dx", 6) or 6),
                       float(form.get("dy", 6) or 6),
                       float(form.get("dz", 6) or 6)],
            "h": float(form.get("h", 0.35) or 0.35),
            "seed": int(form.get("seed", 42) or 42),
            "ncpu": int(form.get("ncpu", 4) or 4),
            "mesh_dfm": bool(form.get("mesh_dfm")),
        }
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
            saved += 1
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
            <pre class="log">{R.esc(chr(10).join(text.splitlines()[:200]))}</pre>
          </details>
        </div>"""
            return self._html(200, target.name, body)
        body = f"""
        <div class="card-head"><h2><code>{R.esc(query.get('path'))}</code></h2>
          <a class="btn" href="/case/{case_id}">← back</a></div>
        <div class="card"><pre class="log">{R.esc(text)}</pre></div>"""
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
