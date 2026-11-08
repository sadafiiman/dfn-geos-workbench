"""Convert a dfnWorks conforming DFM mesh into a GEOS VTK multi-block case.

Usage
-----
    python dfn_to_geos.py --dfm-dir <job>/dfm_mesh --out geos_case \
        [--aperture 1e-4] [--domain 6 6 6]

Input (produced by ``DFN.mesh_network(uniform_mesh=True)`` + ``DFN.mesh_dfm()``)
    dfm_tet_mesh.inp        conforming matrix tetrahedra (LaGriT AVS/UCD)
    facets_merged.inp       fracture triangles sharing matrix nodes
    facets_merged.table     facet -> tet connectivity table (optional use)
    or per fracture:        facets_f<i>.inp / facets_f<i>.table

Output (GEOS proof-of-concept case)
    main.vtu                matrix block (attribute=1), point/cell GlobalIds
    fracture.vtu            face block (triangles), point/cell GlobalIds,
                            collocated_nodes point array, fracture_id +
                            aperture cell fields
    case.vtm                multi-block container ('main' + 'fracture')
    geos_dfn_fractures.xml  ready-to-run GEOS input deck (single-phase flow)

Design notes (from the GEOS source analysis)
    * ``VTKMeshGenerator`` builds cell blocks named ``<regionAttribute>_<type>``
      from an integer cell array (default name ``attribute``).
    * A face block named in ``faceBlocks`` becomes a ``SurfaceElementRegion``
      (``FaceElementSubRegion``) whose elements are the fracture faces.
    * GEOS requires ``GlobalIds`` point+cell arrays (``useGlobalIds="1"``)
      and a ``collocated_nodes`` vtkIdType point array on the face block that
      maps every fracture node to the duplicated global node id(s) in the
      main mesh.  For a conforming DFM mesh each fracture node *is* a matrix
      node, so the mapping is identity after node matching.
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path

import numpy as np

from avs_ucd import read_avs_ucd
from vtk_xml import write_vtm, write_vtu

VTK_TETRA = 10
VTK_TRIANGLE = 5
VTK_PYRAMID = 14
VTK_WEDGE = 13
VTK_HEXAHEDRON = 12


def node_matcher(src_points: np.ndarray, dst_points: np.ndarray,
                 tol: float = 1e-9):
    """Map each source node to the index of the coincident destination node.

    Uses quantised-coordinate hashing so it scales to millions of nodes.
    """
    def key(arr):
        return {tuple(np.round(p, int(-np.log10(tol)) if tol > 0 else 12)): i
                for i, p in enumerate(arr)}

    lut = key(dst_points)
    mapping = np.full(len(src_points), -1, dtype=np.int64)
    for i, p in enumerate(src_points):
        idx = lut.get(tuple(np.round(p, int(-np.log10(tol)) if tol > 0 else 12)))
        if idx is not None:
            mapping[i] = idx
    return mapping


def convert(dfm_dir: str, out_dir: str, aperture: float = 1.0e-4,
            domain: list[float] | None = None,
            xml_title: str = "dfn_fracture_flow",
            ascii_mode: bool = True) -> dict:
    """Build the GEOS case. Returns a small summary dict for the panel UI.

    ascii_mode=True (default) writes ``main.vtu`` fully in ASCII (diffable,
    larger); with ascii_mode=False the matrix point coordinates are written
    as binary float32 (smaller; GEOS/VTK read both identically).
    """
    dfm_dir = Path(dfm_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ matrix
    tet_file = dfm_dir / "dfm_tet_mesh.inp"
    if not tet_file.exists():
        raise FileNotFoundError(
            f"{tet_file} not found. Run DFN.mesh_dfm() first "
            "(requires LaGriT built with exodus).")
    matrix = read_avs_ucd(str(tet_file))
    # keep all 3-D cell types (LaGriT DFM meshes may contain a few pyramids
    # at fracture interfaces) with their VTK type codes
    VOL_TYPES = {"tet": VTK_TETRA, "pyr": VTK_PYRAMID,
                 "pri": VTK_WEDGE, "hex": VTK_HEXAHEDRON}
    blocks = {t: ([], []) for t in VOL_TYPES}  # type -> (nodes, materials)
    for t, nodes, m in zip(matrix.cell_types, matrix.cell_nodes,
                           matrix.cell_materials):
        if t in blocks:
            blocks[t][0].append(nodes)
            blocks[t][1].append(m)
    n_matrix_cells = sum(len(v[0]) for v in blocks.values())
    if not n_matrix_cells:
        raise RuntimeError("dfm_tet_mesh.inp contains no 3-D cells")

    # ---------------------------------------------------------------- fractures
    patterns = ["facets_merged.inp", "facets/facets_merged.inp",
                "facets_f*.inp", "facets/facets_f*.inp"]
    facet_files = []
    for pat in patterns:
        facet_files = sorted(glob.glob(str(dfm_dir / pat)))
        if facet_files:
            break
    if not facet_files:
        raise FileNotFoundError("no facets_*.inp files in " + str(dfm_dir))
    fractures = [read_avs_ucd(f) for f in facet_files]

    # Fracture nodes are a subset of the matrix nodes (conforming mesh):
    # build the collocated_nodes map by coordinate matching.
    node_map = node_matcher(np.vstack([f.points for f in fractures]),
                            matrix.points, tol=1e-7)
    if (node_map < 0).any():
        unmatched = int((node_map < 0).sum())
        raise RuntimeError(f"{unmatched} fracture nodes have no coincident "
                           "matrix node -- meshes are not conforming")

    # Assign GlobalIds: matrix nodes first, then fracture-duplicate nodes.
    # VTK/GEOS global ids are 0-based contiguous (as in GEOS' own .vtu fixtures).
    n_matrix_nodes = matrix.num_nodes
    matrix_point_gid = np.arange(0, n_matrix_nodes, dtype=np.int64)
    matrix_cell_gid = np.arange(0, n_matrix_cells, dtype=np.int64)

    # For every fracture node: global id of the co-located MATRIX node.
    collocated = matrix_point_gid[node_map]

    # Face block: merge all fractures into one face mesh; keep per-fracture id.
    # facets_merged.inp stores the fracture number as the cell material.
    f_points = np.vstack([f.points for f in fractures])
    tri_blocks, f_cell_gid, fracture_id, f_point_gid = [], [], [], []
    gid_offset = n_matrix_nodes  # face nodes get gids *after* matrix nodes
    point_offset = 0
    for k, frac in enumerate(fractures, start=1):
        n_pts = frac.num_nodes
        f_point_gid.extend(range(gid_offset + point_offset,
                                 gid_offset + point_offset + n_pts))
        point_offset += n_pts
        base = sum(len(f.points) for f in fractures[:k - 1])
        local = node_map[base:base + n_pts]
        mats = frac.cell_materials if len(set(frac.cell_materials)) > 1 else None
        for t, nodes, m in zip(frac.cell_types, frac.cell_nodes,
                               frac.cell_materials):
            if t != "tri":
                continue
            tri_blocks.extend(nodes)
            f_cell_gid.append(len(f_cell_gid))
            fracture_id.append(m if mats is not None else k)

    n_fractures = len(set(fracture_id))

    f_point_gid = np.asarray(f_point_gid, dtype=np.int64)
    f_cell_gid = np.asarray(f_cell_gid, dtype=np.int64)
    fracture_id = np.asarray(fracture_id, dtype=np.int32)

    # ---------------------------------------------------------------- write VTK
    matrix_blocks = []
    matrix_attr = []
    for t, (nodes_list, mats) in blocks.items():
        if nodes_list:
            matrix_blocks.append((VOL_TYPES[t],
                                  np.asarray(nodes_list, dtype=np.int64).ravel()))
            matrix_attr.extend(mats)
    write_vtu(out_dir / "main.vtu",
              matrix.points,
              matrix_blocks,
              point_data={"GlobalIds": matrix_point_gid},
              cell_data={"attribute": np.asarray(matrix_attr, dtype=np.int32),
                         "GlobalIds": matrix_cell_gid},
              binary_float32=not ascii_mode)
    write_vtu(out_dir / "fracture.vtu",
              f_points,
              [(VTK_TRIANGLE, np.asarray(tri_blocks, dtype=np.int64).ravel())],
              point_data={"GlobalIds": f_point_gid,
                          "collocated_nodes": collocated.reshape(-1, 1)},
              cell_data={"GlobalIds": f_cell_gid,
                         "fracture_id": fracture_id,
                         "aperture": np.full(len(f_cell_gid), aperture)})

    # one face block per fracture is also supported by GEOS; we emit a single
    # 'fracture' block with a fracture_id field (simpler ElementRegions).
    write_vtm(out_dir / "case.vtm",
              [("main", "main.vtu"), ("fracture", "fracture.vtu")])

    # ------------------------------------------------------------- GEOS deck
    domain = domain or _domain_from_points(matrix.points)
    xml = _geos_flow_deck(xml_title, aperture, domain)
    (out_dir / "geos_dfn_fractures.xml").write_text(xml)

    return {
        "matrix_nodes": matrix.num_nodes,
        "matrix_cells": n_matrix_cells,
        "matrix_types": {t: len(v[0]) for t, v in blocks.items() if v[0]},
        "fractures": n_fractures,
        "fracture_triangles": len(f_cell_gid),
        "output_dir": str(out_dir),
        "xml": str(out_dir / "geos_dfn_fractures.xml"),
        "vtm": str(out_dir / "case.vtm"),
    }


def _domain_from_points(points: np.ndarray) -> list[float]:
    lo, hi = points.min(axis=0), points.max(axis=0)
    pad = 0.01 * max(1.0, float(np.max(hi - lo)))
    return [float(lo[0] - pad), float(hi[0] + pad),
            float(lo[1] - pad), float(hi[1] + pad),
            float(lo[2] - pad), float(hi[2] + pad)]


def _geos_flow_deck(title: str, aperture: float, dom: list[float]) -> str:
    x0, x1, y0, y1, z0, z1 = dom
    pad = 0.01 * max(1.0, x1 - x0, y1 - y0, z1 - z0)
    return f"""<?xml version="1.0" ?>
<Problem>
  <Solvers
      gravityVector="{{ 0.0, 0.0, -9.81 }}">
    <SinglePhaseFVM
      name="SinglePhaseFlow"
      logLevel="1"
      discretization="singlePhaseTPFA"
      targetRegions="{{ Region, Fracture }}">
      <NonlinearSolverParameters
        newtonTol="1.0e-4"
        newtonMaxIter="10"/>
      <LinearSolverParameters
        directParallel="0"/>
    </SinglePhaseFVM>
  </Solvers>

  <Mesh>
    <!-- Multi-block mesh converted from dfnWorks (LaGriT DFM mesh):
         'main'     = surrounding rock matrix (tetrahedra)
         'fracture' = explicit fracture surface (triangles, collocated) -->
    <VTKMesh
      name="dfnMesh"
      file="case.vtm"
      useGlobalIds="1"
      faceBlocks="{{ fracture }}"
      surfacicFieldsToImport="{{ fracture_id, aperture }}"
      surfacicFieldsInGEOS="{{ fractureId, elementAperture }}"/>
  </Mesh>

  <Geometry>
    <Box name="xin"  xMin="{{ {x0 - pad}, {y0 - pad}, {z0 - pad} }}"
                     xMax="{{ {x0 + pad}, {y1 + pad}, {z1 + pad} }}"/>
    <Box name="xout" xMin="{{ {x1 - pad}, {y0 - pad}, {z0 - pad} }}"
                     xMax="{{ {x1 + pad}, {y1 + pad}, {z1 + pad} }}"/>
  </Geometry>

  <Events maxTime="50000">
    <PeriodicEvent name="solverApplications"
                   forceDt="1e3"
                   target="/Solvers/SinglePhaseFlow"/>
    <PeriodicEvent name="outputs"
                   timeFrequency="1e4"
                   target="/Outputs/vtkOutput"/>
  </Events>

  <NumericalMethods>
    <FiniteVolume>
      <TwoPointFluxApproximation name="singlePhaseTPFA"/>
    </FiniteVolume>
  </NumericalMethods>

  <ElementRegions>
    <CellElementRegion
      name="Region"
      cellBlocks="{{ * }}"
      materialList="{{ water, rock }}"/>
    <SurfaceElementRegion
      name="Fracture"
      faceBlock="fracture"
      defaultAperture="{aperture:.6e}"
      materialList="{{ water, fractureFilling }}"/>
  </ElementRegions>

  <Constitutive>
    <CompressibleSinglePhaseFluid
      name="water"
      defaultDensity="1000"
      defaultViscosity="0.001"
      referencePressure="0.0"
      compressibility="5e-10"
      viscosibility="0.0"/>

    <CompressibleSolidConstantPermeability
      name="rock"
      solidModelName="nullSolid"
      porosityModelName="rockPorosity"
      permeabilityModelName="rockPerm"/>

    <CompressibleSolidParallelPlatesPermeability
      name="fractureFilling"
      solidModelName="nullSolid"
      porosityModelName="fracturePorosity"
      permeabilityModelName="fracturePerm"/>

    <NullModel name="nullSolid"/>

    <PressurePorosity
      name="rockPorosity"
      defaultReferencePorosity="0.01"
      referencePressure="0.0"
      compressibility="1.0e-9"/>

    <ConstantPermeability
      name="rockPerm"
      permeabilityComponents="{{ 5.0e-19, 5.0e-19, 5.0e-19 }}"/>

    <PressurePorosity
      name="fracturePorosity"
      defaultReferencePorosity="1.00"
      referencePressure="0.0"
      compressibility="0.0"/>

    <ParallelPlatesPermeability name="fracturePerm"/>
  </Constitutive>

  <FieldSpecifications>
    <FieldSpecification
      name="initialPressure"
      initialCondition="1"
      setNames="{{ all }}"
      objectPath="ElementRegions/Region"
      fieldName="pressure"
      scale="0.0"/>

    <FieldSpecification
      name="initialFracturePressure"
      initialCondition="1"
      setNames="{{ all }}"
      objectPath="ElementRegions/Fracture"
      fieldName="pressure"
      scale="0.0"/>

    <FieldSpecification
      name="source"
      objectPath="ElementRegions/Fracture"
      fieldName="pressure"
      scale="2.0e6"
      setNames="{{ xin }}"/>

    <FieldSpecification
      name="sink"
      objectPath="ElementRegions/Fracture"
      fieldName="pressure"
      scale="1.0e6"
      setNames="{{ xout }}"/>
  </FieldSpecifications>

  <Outputs>
    <VTK name="vtkOutput" format="ascii" plotFileRoot="{title}"/>
  </Outputs>
</Problem>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dfm-dir", required=True,
                    help="dfnWorks dfm_mesh/ directory (dfm_tet_mesh.inp, facets)")
    ap.add_argument("--out", required=True, help="output directory for GEOS case")
    ap.add_argument("--aperture", type=float, default=1.0e-4,
                    help="uniform fracture aperture in metres (default 1e-4)")
    ap.add_argument("--binary", dest="binary", action="store_true",
                    help="write main.vtu point coordinates as binary float32 "
                         "(smaller file; default is ASCII)")
    args = ap.parse_args()
    summary = convert(args.dfm_dir, args.out, aperture=args.aperture,
                      ascii_mode=not args.binary)
    for k, v in summary.items():
        print(f"{k:>22}: {v}")


if __name__ == "__main__":
    main()
