#!/usr/bin/env python3
"""Stage 1b: build the conforming discrete fracture-matrix (DFM) mesh.

Runs dfnWorks' ``mesh_dfm()`` on an existing dfnWorks output directory
(produced by run_dfn_example.py). The DFM mesh is the conforming tetrahedral
mesh of the rock matrix whose faces on the fracture planes coincide with the
fracture triangulation -- the input required for the *conformal* GEOS path.

Outputs (in output/dfm_mesh/):
    dfm_tet_mesh.inp         matrix tetrahedra (AVS/UCD, conforming)
    dfm_tet_mesh.exo         same mesh in Exodus II format
    facets_f<i>.inp/table    per-fracture triangular facets (+ facet->tet table)
    facets_merged.inp/table  all facets merged
"""
import os

for _opt in ("PETSC_DIR", "PETSC_ARCH", "PFLOTRAN_EXE", "FEHM_EXE"):
    os.environ.setdefault(_opt, "")

from pydfnworks import DFNWORKS

SRC = os.path.dirname(os.path.abspath(__file__))
jobname = os.path.join(SRC, "output")


def main():
    os.chdir(jobname)
    DFN = DFNWORKS(jobname, ncpu=4, dfnFlow_file="", dfnTrans_file="")

    # Re-read the state of the finished dfnWorks run from its output files
    # (equivalent to what create_network() does after dfnGen succeeds).
    DFN.parse_params_file()
    DFN.gather_dfn_gen_output()

    # Conforming fracture-matrix mesh (requires LaGriT built with Exodus,
    # which is the case inside the official dfnWorks docker image).
    # allowed_percentage: sliver triangles near intersection lines can be
    # unrecoverable with a uniform background mesh; accept up to 5% of the
    # DFN elements to be absent from the DFM mesh (documented in the report).
    DFN.mesh_dfm(dirname="dfm_mesh", allowed_percentage=5, cleanup=True)
    print("=== DFM meshing complete ===")


if __name__ == "__main__":
    main()
