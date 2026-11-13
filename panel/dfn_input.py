"""Parse dfnGen input decks (``*.dat``) into panel case parameters.

dfnGen stores its *input* in a flat ``key: value`` text format where list
values are curly-brace sets::

    stopCondition: 0
    nPoly: 24
    domainSize: {6.0,6.0,6.0}
    rconst: {2.0,2.0}      // one value per rectangular family

Comments are ``//`` to the end of the line and ``/* ... */`` blocks.  The
panel uses this own stdlib parser to prefill the *Edit DFN* form when a user
uploads a ``.dat`` file; pydfnworks' ``check_input(from_file=True)`` is
deprecated and is deliberately NOT used.

``parse_dfn_dat`` returns a dict with

``params``    updates for the case parameters the panel understands
              (domain, h, seed, n_poly, boundary_faces, ...)
``families``  fracture families in the ``params['families']`` format used by
              ``panel.pipeline`` (kwargs of ``DFN.add_fracture_family``)
``unmapped``  ``{key: rendered value}`` for everything the panel does not
              model, so the edit page can still display it read-only
``notes``     human-readable remarks (e.g. unsupported stopCondition=1)

Limitation: ``famProb`` is indexed per *defined* family, while the ``r*``/
``e*`` arrays are indexed per shape.  When a deck mixes ellipses and
rectangles the original interleaving cannot be recovered from the ``.dat``
alone, so families are read ellipses-first, then rectangles (the order used
by all shipped examples).
"""

from __future__ import annotations

import re

# dfnGen radius-distribution codes (DFNGen Test_Inputs documentation)
DIST_BY_CODE = {1: "log_normal", 2: "tpl", 3: "exp", 4: "constant"}

# per-family array key names, with and without the r-/e- shape prefix
FAMILY_ARRAYS = {
    "distr", "betaDistribution", "orientation_distribution", "beta",
    "_p32Targets", "aspect", "numPoints", "theta", "phi", "trend", "plunge",
    "dip", "strike", "kappa", "kappa1", "kappa2", "LogMean", "sd", "LogMin",
    "LogMax", "alpha", "min", "max", "ExpMean", "ExpMin", "ExpMax", "const",
    "Layer", "Region",
}
_PREFIXED = {p + k for k in FAMILY_ARRAYS for p in ("r", "e")}
_CONSUMED_GLOBALS = {
    "stopCondition", "nPoly", "domainSize", "h", "seed",
    "ignoreBoundaryFaces", "boundaryFaces", "orientationOption",
    "famProb", "nFracFam", "nFamEll", "nFamRect",
}


# ------------------------------------------------------------------ lexing --
def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _split_top(raw: str) -> list[str]:
    """Split on commas at brace depth 0 (defensive: lists may nest)."""
    parts, depth, cur = [], 0, []
    for ch in raw:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


_INT_RE = re.compile(r"[+-]?\d+\Z")


def _parse_token(tok: str):
    if _INT_RE.fullmatch(tok):
        return int(tok)
    try:
        return float(tok)
    except ValueError:
        return tok


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        inner = raw[1:-1].strip()
        return [_parse_token(t) for t in _split_top(inner)] if inner else []
    return _parse_token(raw)


def _fmt_value(val) -> str:
    if isinstance(val, list):
        return "{" + ",".join(_fmt_value(v) for v in val) + "}"
    if isinstance(val, float):
        return f"{val:g}"
    return str(val)


# ----------------------------------------------------------------- mapping --
def _num(val, cast=float, default=None):
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return cast(val)
    return default


def _pick(arr, i, default=None):
    if isinstance(arr, list) and i < len(arr):
        v = arr[i]
        return default if v is None else v
    return default


def _family(prefix: str, i: int, kv: dict, probability: float | None) -> dict:
    """One family from the ``r*``/``e*`` arrays at position *i*."""
    fam: dict = {"shape": "rect" if prefix == "r" else "ell"}
    dist_code = _num(_pick(kv.get(prefix + "distr"), i, 4), int, 4)
    dist = DIST_BY_CODE.get(dist_code, "constant")
    fam["distribution"] = dist
    fam["aspect"] = _num(_pick(kv.get(prefix + "aspect"), i), float, 1.0)
    fam["beta_distribution"] = _num(
        _pick(kv.get(prefix + "betaDistribution"), i), int, 0) or 0
    fam["beta"] = _num(_pick(kv.get(prefix + "beta"), i), float, 0.0)
    fam["trend"] = _num(_pick(kv.get(prefix + "trend"), i), float, 0.0)
    fam["plunge"] = _num(_pick(kv.get(prefix + "plunge"), i), float, 90.0)
    kappa = _num(_pick(kv.get(prefix + "kappa"), i), float)
    if kappa is not None:
        fam["kappa"] = kappa
    if probability is not None:
        fam["probability"] = probability

    if dist == "constant":
        fam["constant"] = _num(_pick(kv.get(prefix + "const"), i), float, 1.0)
    elif dist == "log_normal":
        fam["log_mean"] = _num(_pick(kv.get(prefix + "LogMean"), i), float, 0.0)
        fam["log_std"] = _num(_pick(kv.get(prefix + "sd"), i), float, 0.5)
        lo = _pick(kv.get(prefix + "LogMin"), i)
        if lo is None:
            lo = _pick(kv.get(prefix + "min"), i)
        hi = _pick(kv.get(prefix + "LogMax"), i)
        if hi is None:
            hi = _pick(kv.get(prefix + "max"), i)
        if lo is not None:
            fam["min_radius"] = _num(lo, float)
        if hi is not None:
            fam["max_radius"] = _num(hi, float)
    else:  # tpl / exp use plain min/max (ExpMin/ExpMax written for exp)
        if dist == "tpl":
            fam["alpha"] = _num(_pick(kv.get(prefix + "alpha"), i), float, 2.5)
        else:
            fam["exp_mean"] = _num(_pick(kv.get(prefix + "ExpMean"), i),
                                   float, 1.0)
        lo = _pick(kv.get(prefix + "ExpMin" if dist == "exp" else "min"), i)
        if lo is None:
            lo = _pick(kv.get(prefix + "min"), i)
        hi = _pick(kv.get(prefix + "ExpMax" if dist == "exp" else "max"), i)
        if hi is None:
            hi = _pick(kv.get(prefix + "max"), i)
        fam["min_radius"] = _num(lo, float, 0.1)
        fam["max_radius"] = _num(hi, float, 5.0)
    return fam


def parse_dfn_dat(text: str) -> dict:
    """Parse a dfnGen input deck into panel parameters (see module docstring)."""
    text = _strip_comments(text)
    raw_kv: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        if key:
            raw_kv[key] = raw.strip()
    kv = {k: _parse_value(v) for k, v in raw_kv.items()}

    params: dict = {}
    families: list[dict] = []
    notes: list[str] = []

    # global parameters ------------------------------------------------------
    dom = kv.get("domainSize")
    if isinstance(dom, list) and len(dom) == 3:
        params["domain"] = [_num(v, float, 6.0) for v in dom]
    h = _num(kv.get("h"), float)
    if h is not None:
        params["h"] = h
    seed = _num(kv.get("seed"), int)
    if seed is not None:
        params["seed"] = seed
    ign = _num(kv.get("ignoreBoundaryFaces"), int)
    if ign is not None:
        params["ignore_boundary_faces"] = bool(ign)
    bfaces = kv.get("boundaryFaces")
    if isinstance(bfaces, list) and len(bfaces) == 6:
        params["boundary_faces"] = [_num(v, int, 0) for v in bfaces]
    orient = _num(kv.get("orientationOption"), int)
    if orient is not None:
        params["orientation_option"] = orient

    stop = _num(kv.get("stopCondition"), int)
    if stop == 0:
        n_poly = _num(kv.get("nPoly"), int)
        if n_poly:
            params["n_poly"] = n_poly
    elif stop is not None:
        notes.append(
            "stopCondition=1 (p32 targets) is not editable in the panel; "
            "the family probabilities are imported as relative weights — "
            "set 'Number of fractures' to control the total count.")

    # fracture families ------------------------------------------------------
    n_ell = _num(kv.get("nFamEll"), int, 0) or 0
    n_rect = _num(kv.get("nFamRect"), int, 0) or 0
    n_total = _num(kv.get("nFracFam"), int, n_ell + n_rect) or (n_ell + n_rect)
    probs = kv.get("famProb") if isinstance(kv.get("famProb"), list) else []

    # famProb follows definition order; arrays are per shape.  Ellipses are
    # read first (see module docstring for the interleaving limitation).
    idx = 0
    for prefix, count in (("e", n_ell), ("r", n_rect)):
        for i in range(max(count, 0)):
            prob = _num(_pick(probs, idx if len(probs) == n_total else i,
                              None), float)
            families.append(_family(prefix, i, kv, prob))
            idx += 1
    if families:
        params["n_poly"] = params.get("n_poly") or _num(kv.get("nPoly"), int)

    # everything the panel does not model ------------------------------------
    unmapped: dict[str, str] = {}
    for key, val in kv.items():
        if key in _CONSUMED_GLOBALS:
            continue
        base = key[1:] if len(key) > 1 and key[0] in "re" else None
        if base in FAMILY_ARRAYS and key in _PREFIXED:
            continue
        unmapped[key] = _fmt_value(val)

    return {"params": params, "families": families, "fractures": [],
            "unmapped": unmapped, "keys": sorted(kv), "notes": notes}


def looks_like_dfn_dat(parsed: dict) -> bool:
    """True when the parsed deck carries dfnGen inputs the panel can use."""
    params = parsed.get("params") or {}
    return bool(parsed.get("families")) or any(
        k in params for k in ("domain", "h", "seed", "n_poly",
                              "boundary_faces"))
