#!/usr/bin/env python3
"""Derive a Darcy velocity field from a GEOS pressure solution.

GEOS' ``SinglePhaseFVM`` writes the primary unknown (``pressure``) plus the
cell-centred ``rockPerm_permeability`` but not the velocity.  For the Task-1
proof of concept we reconstruct it from Darcy's law:

    v = -(k / mu) * grad(p)

on the structured matrix mesh (cell centres read from ``elementCenter``).

Usage:
    python derive_velocity.py <geos_matrix.vtu> [--mu 1e-3] [--out DIR]

Writes ``velocity.csv`` and ``velocity.vtu`` next to (or in ``--out``) the
input file.  The output VTU keeps the original points/cells and adds a
three-component ``velocity`` cell array plus ``velocityMagnitude``.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np

ARRAY_RE = r'<DataArray[^>]*Name="%s"[^>]*>(.*?)</DataArray>'


def read_array(text: str, name: str, components: int = 1) -> np.ndarray:
    match = re.search(ARRAY_RE % re.escape(name), text, re.S)
    if not match:
        raise SystemExit(f"array {name!r} not found in the VTU file")
    body = re.sub(r"<InformationKey.*?</InformationKey>", "", match.group(1), flags=re.S)
    values = np.array(body.split(), dtype=float)
    if components > 1:
        values = values.reshape(-1, components)
    return values


def structured_lookup(centres: np.ndarray, tol: float = 1e-6):
    """Map rounded coordinates to cell indices, and find the grid spacing."""
    keys = {tuple(np.round(c, 6)): i for i, c in enumerate(centres)}
    spacings = []
    for axis in range(3):
        unique = np.unique(np.round(centres[:, axis], 6))
        if len(unique) > 1:
            spacings.append(float(np.median(np.diff(unique))))
        else:
            spacings.append(0.0)
    return keys, spacings


def gradient(centres: np.ndarray, pressure: np.ndarray) -> np.ndarray:
    keys, spacing = structured_lookup(centres)
    grad = np.zeros_like(centres)
    rounds = [3 if s > 0 else 0 for s in spacing]
    for axis in range(3):
        h = spacing[axis]
        if h == 0.0:
            continue
        for i, centre in enumerate(centres):
            plus = list(np.round(centre, 6))
            minus = list(np.round(centre, 6))
            plus[axis] = round(plus[axis] + h, 6)
            minus[axis] = round(minus[axis] - h, 6)
            j_plus = keys.get(tuple(plus))
            j_minus = keys.get(tuple(minus))
            if j_plus is not None and j_minus is not None:
                grad[i, axis] = (pressure[j_plus] - pressure[j_minus]) / (2 * h)
            elif j_plus is not None:
                grad[i, axis] = (pressure[j_plus] - pressure[i]) / h
            elif j_minus is not None:
                grad[i, axis] = (pressure[i] - pressure[j_minus]) / h
    return grad


def write_vtu(path: Path, text: str, velocity: np.ndarray) -> None:
    magnitude = np.linalg.norm(velocity, axis=1)
    pieces = re.search(r"(<Piece.*?</Piece>)", text, re.S)
    if not pieces:
        raise SystemExit("no <Piece> section found")

    def fmt(array: np.ndarray) -> str:
        flat = array.reshape(-1)
        return " ".join(f"{v:.9g}" for v in flat)

    block = (
        f'<DataArray type="Float64" Name="velocity" '
        f'NumberOfComponents="3" format="ascii">\n{fmt(velocity)}\n</DataArray>\n'
        f'<DataArray type="Float64" Name="velocityMagnitude" format="ascii">\n'
        f'{fmt(magnitude)}\n</DataArray>'
    )
    piece = pieces.group(1)
    if "<CellData>" in piece:
        piece = piece.replace("</CellData>", block + "\n</CellData>", 1)
    else:  # pragma: no cover - GEOS always emits CellData here
        piece = piece.replace("</Piece>", "<CellData>\n" + block + "\n</CellData>\n</Piece>", 1)
    path.write_text(text.replace(pieces.group(1), piece))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("vtu", type=Path)
    ap.add_argument("--mu", type=float, default=1e-3, help="dynamic viscosity [Pa s]")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    text = args.vtu.read_text()
    centres = read_array(text, "elementCenter", 3)
    pressure = read_array(text, "pressure")
    perm = read_array(text, "rockPerm_permeability", 3)

    grad = gradient(centres, pressure)
    velocity = -(perm / args.mu) * grad

    out_dir = args.out or args.vtu.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "velocity.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["cell", "x", "y", "z", "vx", "vy", "vz", "|v|"])
        for i in range(len(velocity)):
            writer.writerow([i, *centres[i], *velocity[i],
                             float(np.linalg.norm(velocity[i]))])

    write_vtu(out_dir / "velocity.vtu", text, velocity)
    speed = np.linalg.norm(velocity, axis=1)
    print(f"cells: {len(speed)}")
    print(f"|v| min/median/max: {speed.min():.4g} / "
          f"{np.median(speed):.4g} / {speed.max():.4g} m/s")
    print(f"wrote {out_dir / 'velocity.csv'} and {out_dir / 'velocity.vtu'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
