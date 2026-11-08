"""Reconstruct a dfnWorks fracture network as GEOS EDFM geometry (Option C).

Reads the stochastic/user fracture definitions that dfnWorks exports
(``polys/poly_<i>.inp`` outline polygons + ``params.txt``) and generates a
GEOS input deck in which

  * the rock matrix is an ``InternalMesh`` hexahedral grid of the same domain;
  * every dfnWorks fracture becomes an oriented ``Rectangle`` planar geometric
    object;
  * an ``EmbeddedSurfaceGenerator`` discretises those planes into embedded
    surface elements inside the matrix cells (EDFM);
  * flow runs with ``SinglePhaseFVM`` (TPFA) on ``{ RockMatrix, Fracture }``.

This path works with any dfnWorks run (no matrix mesh needed) and preserves
the fracture geometry, orientation, and connectivity *as geometric objects*;
the numerical fracture-matrix coupling is then computed by GEOS itself.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from avs_ucd import read_avs_ucd


def read_domain(params_path: Path) -> tuple[list[float], float, int]:
    """Parse dfnWorks params.txt (positional format).

    Line 1: number of fractures, line 2: mesh resolution h, line 3: visual
    mode, line 4: expected dudded points, lines 5-7: domain size x y z.
    """
    lines = [ln.strip() for ln in params_path.read_text().splitlines()
             if ln.strip()]
    num_frac = int(float(lines[0]))
    h = float(lines[1])
    size = [float(lines[4]), float(lines[5]), float(lines[6])]
    return size, h, num_frac


def fracture_rectangles(job_dir: Path) -> list[dict]:
    """Extract an oriented bounding rectangle for every fracture polygon."""
    polys = sorted((job_dir / "polys").glob("poly_*.inp"),
                   key=lambda p: int(p.stem.split("_")[1]))
    out = []
    for path in polys:
        fid = int(path.stem.split("_")[1])
        mesh = read_avs_ucd(str(path))
        pts = mesh.points
        c = pts.mean(axis=0)
        # plane fit: smallest singular vector of the covariance matrix
        cov = np.cov((pts - c).T)
        _, eigv = np.linalg.eigh(cov)
        n = eigv[:, 0]
        u = eigv[:, 2]
        v = np.cross(n, u)
        u /= np.linalg.norm(u)
        v /= np.linalg.norm(v)
        local = np.column_stack([(pts - c) @ u, (pts - c) @ v])
        length = float(local[:, 0].max() - local[:, 0].min())
        width = float(local[:, 1].max() - local[:, 1].min())
        # centre of the bounding rectangle inside the plane
        ctr = c + u * (local[:, 0].max() + local[:, 0].min()) / 2 \
                + v * (local[:, 1].max() + local[:, 1].min()) / 2
        out.append({"id": fid, "origin": ctr, "normal": n, "u": u, "v": v,
                    "dimensions": [length, width]})
    return out


def fmt_vec3(a) -> str:
    return "{ " + ", ".join(f"{x:.8g}" for x in a) + " }"


def build_edfm_deck(job_dir: Path, out_dir: Path, aperture: float = 1.0e-4,
                    matrix_cells_per_side: int = 20) -> dict:
    params_path = job_dir / "params.txt"
    dom, h, num_frac = read_domain(params_path)
    fracs = fracture_rectangles(job_dir)
    if not fracs:
        raise RuntimeError("no polys/poly_*.inp outlines found in " + str(job_dir))

    out_dir.mkdir(parents=True, exist_ok=True)
    n = matrix_cells_per_side
    cx = dom[0] / n  # thickness of one matrix cell layer in x
    rect_xml = []
    for f in fracs:
        rect_xml.append(f"""    <Rectangle
      name="Fracture{f['id']}"
      origin="{fmt_vec3(f['origin'])}"
      normal="{fmt_vec3(f['normal'])}"
      lengthVector="{fmt_vec3(f['u'])}"
      widthVector="{fmt_vec3(f['v'])}"
      dimensions="{{ {f['dimensions'][0]:.6f}, {f['dimensions'][1]:.6f} }}"/>""")
    target_objects = ", ".join(f"Fracture{f['id']}" for f in fracs)

    xml = f"""<?xml version="1.0" ?>
<Problem>
  <!-- Proof of concept (Option C): dfnWorks fracture network rebuilt as
       GEOS embedded discrete fractures (EDFM).
       Source: dfnWorks run in {job_dir.name} ({len(fracs)} fractures,
       domain {dom[0]}x{dom[1]}x{dom[2]} m, h = {h} m). -->
  <Solvers
      gravityVector="{{ 0.0, 0.0, -9.81 }}">
    <SinglePhaseFVM
      name="SinglePhaseFlow"
      logLevel="1"
      discretization="singlePhaseTPFA"
      targetRegions="{{ RockMatrix, Fracture }}">
      <NonlinearSolverParameters
        newtonTol="1.0e-4"
        newtonMaxIter="10"/>
      <LinearSolverParameters
        directParallel="0"/>
    </SinglePhaseFVM>

    <EmbeddedSurfaceGenerator
      name="SurfaceGenerator"
      logLevel="1"
      discretization="FE1"
      targetRegions="{{ RockMatrix, Fracture }}"
      targetObjects="{{ {target_objects} }}"
      fractureRegion="Fracture"
      mpiCommOrder="1"/>
  </Solvers>

  <Mesh>
    <InternalMesh
      name="matrix"
      elementTypes="{{ C3D8 }}"
      xCoords="{{ {-dom[0] / 2}, {dom[0] / 2} }}"
      yCoords="{{ {-dom[1] / 2}, {dom[1] / 2} }}"
      zCoords="{{ {-dom[2] / 2}, {dom[2] / 2} }}"
      nx="{{ {n} }}"
      ny="{{ {n} }}"
      nz="{{ {n} }}"
      cellBlockNames="{{ cb1 }}"/>
  </Mesh>

  <Geometry>
{chr(10).join(rect_xml)}

    <Box name="source" xMin="{{ {-dom[0] / 2 - 0.01:.6g}, {-dom[1] / 2 - 0.01:.6g}, {-dom[2] / 2 - 0.01:.6g} }}"
                        xMax="{{ {-dom[0] / 2 + cx:.6g}, {dom[1] / 2 + 0.01:.6g}, {dom[2] / 2 + 0.01:.6g} }}"/>
    <Box name="sink"   xMin="{{ {dom[0] / 2 - cx - 0.01:.6g}, {-dom[1] / 2 - 0.01:.6g}, {-dom[2] / 2 - 0.01:.6g} }}"
                       xMax="{{ {dom[0] / 2 + 0.01:.6g}, {dom[1] / 2 + 0.01:.6g}, {dom[2] / 2 + 0.01:.6g} }}"/>
  </Geometry>

  <Events maxTime="50000">
    <SoloEvent
      name="preFracture"
      target="/Solvers/SurfaceGenerator"/>
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
    <FiniteElements>
      <FiniteElementSpace name="FE1" order="1"/>
    </FiniteElements>
  </NumericalMethods>

  <ElementRegions>
    <CellElementRegion
      name="RockMatrix"
      cellBlocks="{{ cb1 }}"
      materialList="{{ water, rock }}"/>
    <SurfaceElementRegion
      name="Fracture"
      defaultAperture="{aperture:.6e}"
      materialList="{{ water, fractureFilling }}"
      subRegionType="embeddedElement"/>
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
      objectPath="ElementRegions/RockMatrix"
      fieldName="pressure"
      scale="0.0"/>
    <FieldSpecification
      name="source"
      objectPath="ElementRegions/RockMatrix"
      fieldName="pressure"
      scale="2.0e6"
      setNames="{{ source }}"/>
    <FieldSpecification
      name="sink"
      objectPath="ElementRegions/RockMatrix"
      fieldName="pressure"
      scale="1.0e6"
      setNames="{{ sink }}"/>
  </FieldSpecifications>

  <Outputs>
    <VTK name="vtkOutput" format="ascii" plotFileRoot="dfn_edfm"/>
  </Outputs>
</Problem>
"""
    xml_path = out_dir / "geos_dfn_edfm.xml"
    xml_path.write_text(xml)
    return {
        "fractures": len(fracs),
        "num_frac_expected": num_frac,
        "domain": dom,
        "h": h,
        "xml": str(xml_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job-dir", required=True,
                    help="dfnWorks output directory (params.txt + polys/)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--aperture", type=float, default=1.0e-4)
    args = ap.parse_args()
    summary = build_edfm_deck(Path(args.job_dir), Path(args.out),
                              aperture=args.aperture)
    for k, v in summary.items():
        print(f"{k:>12}: {v}")


if __name__ == "__main__":
    main()
