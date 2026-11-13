"""Server-rendered SVG previews of the fracture network (no JavaScript).

Two sources:

* **params** — the user fractures exactly as defined plus the stochastic
  families *sampled deterministically* with numpy (same seed as the dfnWorks
  run).  This is an approximation of what dfnGen will generate, good enough
  to judge size, orientation and density before spending a meshing run.
* **case** — the real fracture polygons dfnWorks wrote to
  ``output/polys/poly_*.inp`` after a mesh run (the ground truth).

Every fracture is projected onto the XY, XZ and YZ planes and drawn as
inline SVG, so the panel needs no canvas/WebGL and works in any browser.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

PALETTE = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
           "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f")

SAMPLE_DEFAULT = 24          # when n_poly is not set (driver default)
ELL_SAMPLES = 16             # polygon points used to draw an ellipse


# ----------------------------------------------------------------- params --
def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two orthonormal in-plane vectors for a given unit normal."""
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(normal, ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    u = np.cross(normal, ref)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    return u, v


def _trend_plunge_normal(trend_deg: float, plunge_deg: float) -> np.ndarray:
    """Unit normal from dfnGen orientationOption=1 trend/plunge (degrees)."""
    t = math.radians(trend_deg)
    p = math.radians(plunge_deg)
    return np.array([math.cos(p) * math.cos(t),
                     math.cos(p) * math.sin(t),
                     math.sin(p)])


def _sample_radius(fam: dict, rng: np.random.Generator) -> float:
    dist = fam.get("distribution", "constant")
    if dist == "constant":
        return float(fam.get("constant", 2.0))
    if dist == "log_normal":
        r = float(np.exp(rng.normal(float(fam.get("log_mean", 0.0)),
                                    float(fam.get("log_std", 0.5)))))
    elif dist == "tpl":
        # truncated power-law p(r) ~ r^-alpha on [min, max] (inverse CDF)
        alpha = float(fam.get("alpha", 2.5))
        lo = float(fam.get("min_radius", 0.1))
        hi = float(fam.get("max_radius", 5.0))
        u = rng.random()
        e = 1.0 - alpha
        r = (u * (hi ** e - lo ** e) + lo ** e) ** (1.0 / e) if e != 0 \
            else lo * (hi / lo) ** u
    else:  # exp
        r = float(rng.exponential(float(fam.get("exp_mean", 1.0))))
    lo = fam.get("min_radius")
    hi = fam.get("max_radius")
    if lo is not None:
        r = max(r, float(lo))
    if hi is not None:
        r = min(r, float(hi))
    return r


def _fracture_polygon(center, normal, half_len, half_wid,
                      shape: str) -> list[list[float]]:
    """Polygon corners of one fracture (rect: rectangle, ell: ellipse)."""
    n = np.asarray(normal, float)
    n /= np.linalg.norm(n)
    u, v = _plane_basis(n)
    c = np.asarray(center, float)
    if shape == "ell":
        ts = np.linspace(0.0, 2.0 * math.pi, ELL_SAMPLES, endpoint=False)
        return [list(c + u * (half_len * math.cos(t))
                     + v * (half_wid * math.sin(t))) for t in ts]
    return [list(c + su * u * half_len + sv * v * half_wid)
            for su, sv in ((1, 1), (1, -1), (-1, -1), (-1, 1))]


def fractures_from_params(params: dict) -> dict:
    """Fractures the current parameters describe (user exact, families sampled)."""
    params = params or {}
    out: list[dict] = []
    color_i = 0

    for f in params.get("fractures") or []:
        r = float(f.get("radii", 0.5))
        aspect = float(f.get("aspect_ratio") or 1.0)
        normal = np.asarray(f.get("normal") or [0.0, 0.0, 1.0], float)
        if not np.linalg.norm(normal):
            normal = np.array([0.0, 0.0, 1.0])
        out.append({
            "shape": f.get("shape", "rect"),
            "points": _fracture_polygon(f.get("translation") or [0.0, 0.0, 0.0],
                                        normal, r, r * aspect,
                                        f.get("shape", "rect")),
            "color": PALETTE[color_i % len(PALETTE)],
        })
        color_i += 1

    families = list(params.get("families") or [])
    if not families and not out:
        # mirror the driver's default two orthogonal families
        families = [
            {"distribution": "constant", "constant": 2.0, "aspect": 1.0,
             "trend": 0.0, "plunge": 0.0},
            {"distribution": "constant", "constant": 2.0, "aspect": 1.0,
             "trend": 35.0, "plunge": 90.0},
        ]
    if families:
        n = int(params.get("n_poly") or SAMPLE_DEFAULT)
        weights = np.array([float(f.get("probability", 1.0)) for f in families])
        weights = weights / weights.sum()
        rng = np.random.default_rng(int(params.get("seed", 42)))
        domain = [float(v) for v in (params.get("domain") or [6.0] * 3)]
        for fam_i in rng.choice(len(families), size=n, p=weights):
            fam = families[int(fam_i)]
            r = _sample_radius(fam, rng)
            aspect = float(fam.get("aspect", 1.0) or 1.0)
            normal = _trend_plunge_normal(float(fam.get("trend", 0.0)),
                                          float(fam.get("plunge", 90.0)))
            center = [rng.uniform(-d / 2.0, d / 2.0) for d in domain]
            shape = fam.get("shape", "rect")
            out.append({
                "shape": shape,
                "points": _fracture_polygon(center, normal, r, r * aspect,
                                            shape),
                "color": PALETTE[(1 + fam_i) % len(PALETTE)],
            })

    return {"fractures": out,
            "domain": [float(v) for v in (params.get("domain") or [6.0] * 3)],
            "sampled": bool(params.get("families")) or not params.get("fractures")}


# ------------------------------------------------------------------- case --
def _load_avs_ucd():
    import sys
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from conversion.avs_ucd import read_avs_ucd  # noqa: PLC0415
    return read_avs_ucd


def fractures_from_case(case_dir: Path) -> dict | None:
    """The real fracture outlines from a dfnWorks run, or None if absent."""
    case_dir = Path(case_dir)
    from .ingest import resolve_dfn_outputs
    _dfm, job_dir = resolve_dfn_outputs(case_dir)
    polys = sorted(job_dir.glob("polys/poly_*.inp"),
                   key=lambda p: int(p.stem.split("_")[-1])) \
        if job_dir else []
    if not polys:
        return None

    domain, h = [6.0, 6.0, 6.0], None
    params_txt = job_dir / "params.txt" if job_dir else None
    if params_txt and params_txt.exists():
        lines = [ln.strip() for ln in params_txt.read_text().splitlines()
                 if ln.strip()]
        try:
            domain = [float(lines[4]), float(lines[5]), float(lines[6])]
            h = float(lines[1])
        except (IndexError, ValueError):
            pass

    read_avs = _load_avs_ucd()
    out = []
    for path in polys:
        fid = int(path.stem.split("_")[-1])
        mesh = read_avs(str(path))
        pts = mesh.points
        tris = [nodes for t, nodes in zip(mesh.cell_types, mesh.cell_nodes)
                if t in ("tri", "quad") and len(nodes) >= 3]
        loops = []
        if tris:
            pass                       # triangulated outline: draw as-is
        else:
            # dfnGen writes the fracture boundary as 'line' cells (often an
            # open chain missing the closing edge) — chain them into loops.
            loops = _chain_edges(
                [(nodes[0], nodes[-1])
                 for t, nodes in zip(mesh.cell_types, mesh.cell_nodes)
                 if t == "line" and len(nodes) >= 2])
            if not loops:
                loops = [list(range(len(pts)))]
        out.append({"id": fid, "points3d": pts, "tris": tris, "loops": loops,
                    "color": PALETTE[fid % len(PALETTE)]})
    return {"fractures": out, "domain": domain, "h": h,
            "num_frac": len(out), "real": True}


def _chain_edges(edges: list[tuple[int, int]]) -> list[list[int]]:
    """Join undirected edges into continuous node loops/chains."""
    adj: dict[int, list[int]] = {}
    for a, b in edges:
        if a != b:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    loops: list[list[int]] = []
    while adj:
        start = min(adj, key=lambda n: (len(adj[n]), n))
        loop = [start]
        prev, cur = None, start
        while True:
            nxts = [n for n in adj.get(cur, []) if n != prev]
            if not nxts:
                break
            prev, cur = cur, nxts[0]
            if cur == start:
                break
            loop.append(cur)
        for a, b in zip(loop, loop[1:]):
            adj.get(a, []).remove(b)
            adj.get(b, []).remove(a)
            if not adj.get(a):
                adj.pop(a, None)
            if not adj.get(b):
                adj.pop(b, None)
        adj.pop(start, None)
        if len(loop) >= 2:
            loops.append(loop)
    return loops


# ------------------------------------------------------------------- svg ---
_PROJECTIONS = (("XY", 0, 1, "x →", "y ↑"), ("XZ", 0, 2, "x →", "z ↑"),
                ("YZ", 1, 2, "y →", "z ↑"))


def _poly_paths(points: list[list[float]], ai: int, bi: int,
                flip: bool) -> str:
    seg = []
    for p in points:
        a, b = p[ai], p[bi]
        if flip:
            b = -b
        seg.append(f"{a:.3g},{b:.3g}")
    return " ".join(seg)


def svg_network(data: dict, px: int = 300) -> dict:
    """Render the three projections as inline SVG strings."""
    domain = data.get("domain") or [6.0, 6.0, 6.0]
    svgs = {}
    for title, ai, bi, ax_lab, b_lab in _PROJECTIONS:
        da, db = max(domain[ai], 1e-6), max(domain[bi], 1e-6)
        w = px
        hgt = int(round(px * db / da))
        pad = 6
        parts = [f'<svg class="net" viewBox="{-da / 2 - pad:.3g} '
                 f'{-db / 2 - pad:.3g} {da + 2 * pad:.3g} {db + 2 * pad:.3g}" '
                 f'width="{w}" height="{hgt}" role="img" '
                 f'aria-label="{title} projection">']
        parts.append(f'<rect x="{-da / 2:.3g}" y="{-db / 2:.3g}" '
                     f'width="{da:.3g}" height="{db:.3g}" fill="#fafafa" '
                     f'stroke="#9aa4b2" stroke-dasharray="4 3"/>')
        for fr in data.get("fractures") or []:
            color = fr.get("color", "#1f77b4")
            if fr.get("tris"):               # triangulated dfnWorks polygons
                pts = fr["points3d"]
                for nodes in fr["tris"]:
                    tri = [pts[i] for i in nodes[:3]]
                    parts.append(
                        f'<polygon points="{_poly_paths(tri, ai, bi, bi == 2)}" '
                        f'fill="{color}" fill-opacity="0.10" '
                        f'stroke="{color}" stroke-opacity="0.7" '
                        f'stroke-width="{0.004 * da:.4g}"/>')
            for loop in fr.get("loops") or []:   # chained line outlines
                ring = [fr["points3d"][i] for i in loop]
                path = _poly_paths(ring, ai, bi, bi == 2)
                parts.append(
                    f'<polygon points="{path}" fill="{color}" '
                    f'fill-opacity="0.12" stroke="{color}" '
                    f'stroke-width="{0.006 * da:.4g}"/>')
            if not fr.get("tris") and not fr.get("loops"):
                path = _poly_paths(fr["points"], ai, bi, bi == 2)
                parts.append(
                    f'<polygon points="{path}" fill="{color}" '
                    f'fill-opacity="0.15" stroke="{color}" '
                    f'stroke-width="{0.006 * da:.4g}"/>')
        parts.append('</svg>')
        label = (f'<div class="net-fig"><div class="net-title">{title}</div>'
                 + "".join(parts)
                 + f'<div class="net-axes">{ax_lab} &nbsp;·&nbsp; {b_lab}</div>'
                 f'</div>')
        svgs[title.lower()] = label
    return svgs


def count_label(data: dict) -> str:
    n = len(data.get("fractures") or [])
    if data.get("real"):
        extra = f", h = {data['h']:g} m" if data.get("h") else ""
        return f"{n} fractures generated by dfnWorks{extra}"
    sampled = " (families sampled with the case seed)" if data.get("sampled") \
        else ""
    return f"{n} fractures{sampled} — preview from the current parameters"


def params_preview_html(params: dict) -> str:
    """Full preview card HTML from case parameters (edit page + case page)."""
    data = fractures_from_params(params)
    svgs = svg_network(data)
    return ("<div class='net-row'>" + svgs["xy"] + svgs["xz"] + svgs["yz"]
            + "</div><p class='muted'>" + count_label(data) + "</p>")


def case_preview_html(case_dir: Path, params: dict) -> str:
    """Preview card HTML: real dfnWorks polygons when present, else params."""
    data = fractures_from_case(case_dir)
    if data is None:
        return ""
    svgs = svg_network(data)
    return ("<div class='net-row'>" + svgs["xy"] + svgs["xz"] + svgs["yz"]
            + "</div><p class='muted'>" + count_label(data) + "</p>")
