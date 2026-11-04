#!/usr/bin/env python3
"""Task 1.1 -- Run a dfnWorks generation + meshing example.

Adapted from the canonical ``examples/constant`` driver shipped with dfnWorks
(constant-size rectangular fracture families, FRAM rejection sampling), with
a reduced network size so it runs on a laptop:

    1. create_network()  -> dfnGen: stochastic fracture generation
    2. mesh_network()    -> LaGriT: conforming Delaunay triangulation of the DFN
    3. lagrit2pflotran() -> UGE conversion: full_mesh_vol_area.uge with
                            corrected cell volumes / face areas

Outputs examined by the feasibility study land in ``output/``:
    full_mesh.inp           AVS/UCD unstructured mesh (tets + triangles)
    full_mesh.uge           UGE node/element/cell list
    full_mesh_vol_area.uge  UGE with corrected volumes/areas
    materialid.dat          fracture id per mesh node
    intersection_list.dat   fracture-fracture intersections
    poly_info.dat           fracture polygon definition data
"""
import os
import sys

# Optional solver paths: keep them defined (empty) so pydfnworks' path
# printer does not KeyError when PFLOTRAN/FEHM/PETSc are not installed.
# This keeps the workflow meshing-only (no flow simulation).
for _optional in ("PETSC_DIR", "PETSC_ARCH", "PFLOTRAN_EXE", "FEHM_EXE"):
    os.environ.setdefault(_optional, "")

from pydfnworks import DFNWORKS

SRC = os.path.dirname(os.path.abspath(__file__))
jobname = os.path.join(SRC, "output")


def main():
    DFN = DFNWORKS(jobname, ncpu=4, dfnFlow_file="", dfnTrans_file="")

    # Same structure as examples/constant, scaled down for laptop runs.
    DFN.params["domainSize"]["value"] = [6.0, 6.0, 6.0]
    DFN.params["h"]["value"] = 0.35
    DFN.params["orientationOption"]["value"] = 1
    DFN.params["stopCondition"]["value"] = 0
    DFN.params["nPoly"]["value"] = 24
    DFN.params["seed"]["value"] = 6969420
    # flow enters through +X / -X boundaries (as in the original example)
    DFN.params["boundaryFaces"]["value"] = [1, 1, 0, 0, 0, 0]

    # Two orthogonal fracture families with constant radii 2.0
    DFN.add_fracture_family(shape="rect",
                            distribution="constant",
                            kappa=20.0,
                            probability=1.0,
                            aspect=1.0,
                            beta_distribution=1,
                            beta=0.0,
                            trend=0.0,
                            plunge=0.0,
                            constant=2.0,
                            hy_variable="transmissivity",
                            hy_function="correlated",
                            hy_params={"alpha": 1e-13, "beta": 1})

    DFN.add_fracture_family(shape="rect",
                            distribution="constant",
                            kappa=20.0,
                            probability=1.0,
                            aspect=1.0,
                            beta_distribution=1,
                            beta=0.0,
                            trend=35.0,
                            plunge=90.0,
                            constant=2.0,
                            hy_variable="transmissivity",
                            hy_function="correlated",
                            hy_params={"alpha": 1e-13, "beta": 1})

    DFN.make_working_directory(delete=True)
    DFN.check_input()
    DFN.print_domain_parameters()

    DFN.create_network()
    DFN.mesh_network(uniform_mesh=True)

    # Convert to UGE with corrected volumes/areas (uses CPP_correct_volumes)
    DFN.lagrit2pflotran()
    print("\n=== dfnWorks meshing complete; outputs in", jobname, "===")


if __name__ == "__main__":
    main()
