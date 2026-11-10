"""Upload ingestion: safe ZIP extraction and input auto-detection.

Used by the panel's "Quick process" page so a user can drop a ZIP (or a few
files) and have the correct pipeline stage(s) run automatically.

Recognised content
------------------
* dfnWorks **outputs**      -> ``full_mesh.inp``, ``params.txt``, ``poly_info.dat``,
  ``materialid.dat``, ``polys/``, optional ``dfm_mesh/dfm_tet_mesh.inp`` + facets
* dfnWorks **driver/inputs** -> ``dfn_driver.py``, ``input_generator.dat``,
  ``case_params.json``
* **GEOS case**             -> ``*.xml`` alone (self-contained decks such as the
  EDFM one the panel generates) or with ``*.vtm`` / ``*.vtu`` / ``*.vtp``

Typical actions produced
------------------------
``convert``  : dfnWorks outputs are present  -> run the converter
``dfn_mesh`` : only inputs/driver present    -> run dfnWorks, then convert
``geos``     : a GEOS XML deck is present    -> run GEOS on that exact deck
``full``     : nothing recognisable          -> dfnWorks -> convert -> GEOS
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

DFN_OUTPUT_HINTS = ("full_mesh.inp", "params.txt", "poly_info.dat",
                    "materialid.dat", "intersection_list.dat")
DFN_DRIVER_HINTS = ("dfn_driver.py", "input_generator.dat",
                    "case_params.json", "input_generator_clean.dat")
MESH_SUFFIXES = (".vtm", ".vtu", ".vtp", ".vti", ".exo", ".e", ".msh")


def is_runnable_deck(path: Path) -> bool:
    """True for a standalone GEOS deck (not a fragment included by another)."""
    stem = path.stem.lower()
    if stem.endswith("_base") or stem.endswith("-base"):
        return False
    try:
        head = path.read_text(errors="ignore")[:8000]
    except OSError:
        return False
    return re.search(r"<Problem[\s>]", head) is not None


def pick_deck(files: list[str], root: Path) -> str:
    """Choose the most likely runnable GEOS deck among relative paths."""
    xmls = [f for f in files if f.lower().endswith(".xml")]
    if not xmls:
        return ""

    def rank(rel: str) -> tuple:
        name = Path(rel).name.lower()
        return (0 if name.startswith("geos_dfn_") else 1,
                0 if name.endswith("_edfm.xml") else 1,
                len(Path(rel).parts), rel)

    for rel in sorted(xmls, key=rank):
        if is_runnable_deck(root / rel):
            return rel
    return sorted(xmls, key=rank)[0]


def safe_extract_zip(zip_bytes: bytes, dest: Path) -> list[str]:
    """Extract a ZIP into ``dest``, ignoring unsafe paths. Returns rel paths.

    A single common top-level folder is stripped (the usual "zip -r folder"
    layout) so that contents land directly in the destination.
    """
    written: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        names = [[p for p in PurePosixPath(i.filename).parts
                  if p not in ("", ".", "..")] for i in infos]
        # strip a shared leading directory
        strip = 0
        if names and all(len(n) > 1 for n in names):
            first = names[0][0]
            if all(n[0] == first for n in names):
                strip = 1
        for info, parts in zip(infos, names):
            parts = parts[strip:]
            if not parts:
                continue
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            written.append("/".join(parts))
    return written


def place_loose_files(files, dest: Path) -> list[str]:
    """Save uploaded loose files, routing dfnWorks outputs into ``output/``."""
    written = []
    for _field, filename, data in files:
        if not filename:
            continue
        name = Path(filename).name
        sub = "output" if name in DFN_OUTPUT_HINTS or name.endswith(".dat") \
            else ""
        target = dest / sub / name if sub else dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append("/".join(p for p in (sub, name) if p))
    return written


def detect_action(files: list[str], geos_configured: bool,
                  case_dir: Path | None = None) -> dict:
    """Inspect extracted/uploaded relative paths and choose a pipeline."""
    low = [f.lower() for f in files]
    has_dfm = any(f.endswith("dfm_tet_mesh.inp") for f in low)
    has_dfn_out = any(Path(f).name in DFN_OUTPUT_HINTS for f in low)
    has_driver = any(Path(f).name in DFN_DRIVER_HINTS for f in low)
    has_deck = any(f.endswith(".xml") for f in low) and (
        case_dir is None or any(is_runnable_deck(Path(case_dir) / f)
                                for f in files if f.lower().endswith(".xml")))
    has_mesh = any(f.endswith(MESH_SUFFIXES) for f in low)

    if has_dfm or has_dfn_out:
        action, why = "convert", ("found dfnWorks mesh outputs"
                                  + (" (conforming DFM mesh)" if has_dfm
                                     else " (DFN surface mesh)"))
    elif has_deck:
        action, why = "geos", ("found a GEOS input deck"
                               + ("" if has_mesh else
                                  " (self-contained: no mesh files needed)"))
    elif has_driver:
        action, why = "full", "found dfnWorks input/driver files"
    elif any(f.endswith(".xml") for f in low):
        action, why = "geos", "found a GEOS XML file"
    else:
        action, why = "full", "no recognisable inputs (running the full pipeline)"

    chain = _chain_for(action, geos_configured)
    deck = pick_deck(files, Path(case_dir)) if case_dir else ""
    return {"action": action, "reason": why, "chain": chain, "deck": deck,
            "has_dfm": has_dfm, "has_dfn_outputs": has_dfn_out,
            "has_geos_xml": any(f.endswith(".xml") for f in low)}


def _chain_for(action: str, geos_configured: bool) -> list[str]:
    if action == "full":
        chain = ["dfn_mesh", "convert_to_geos"]
        if geos_configured:
            chain.append("run_geos")
        return chain
    if action == "convert":
        return ["convert_to_geos"]
    if action == "geos":
        return ["run_geos"]
    return []


def resolve_dfn_outputs(case_dir: Path) -> tuple[Path | None, Path | None]:
    """Locate (dfm_dir, job_dir) anywhere under a case directory.

    Returns the directory containing ``dfm_tet_mesh.inp`` (if present) and the
    dfnWorks job directory (containing ``params.txt`` / ``polys/``).
    """
    dfm_dir = None
    for p in sorted(case_dir.rglob("dfm_tet_mesh.inp")):
        dfm_dir = p.parent
        break
    job_dir = None
    for p in sorted(case_dir.rglob("params.txt")):
        if (p.parent / "polys").is_dir() or \
                (p.parent / "full_mesh.inp").exists():
            job_dir = p.parent
            break
    if job_dir is None:
        for p in sorted(case_dir.rglob("full_mesh.inp")):
            job_dir = p.parent
            break
    return dfm_dir, job_dir
