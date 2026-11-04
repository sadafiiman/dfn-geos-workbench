"""dfnWorks -> GEOS mesh conversion package.

Task 1 / Option B of the feasibility assessment: convert dfnWorks output
(AVS/UCD ``.inp`` meshes written by LaGriT) into GEOS-consumable VTK XML
files (``.vtu`` / ``.vtp`` / ``.vtm``) plus a ready-to-run GEOS input deck.

Supported conversions
---------------------
1.  Conforming DFM mesh (``mesh_dfm()`` output) ->
    ``main`` block (matrix tetrahedra) + ``fracture`` face block (triangles)
    with GlobalIds and ``collocated_nodes`` -> conformal fracture flow in GEOS
    (``SurfaceElementRegion`` with ``subRegionType="faceElement"``).

2.  DFN fracture surface mesh (``full_mesh.inp``) + fracture outlines
    (``polys/poly_N.inp``) -> GEOS ``Rectangle`` geometric objects for the
    EDFM path (``SurfaceElementRegion`` with ``subRegionType="embeddedElement"``).

Everything is written with the standard library only (no pyvista / meshio),
so the converter runs identically on Ubuntu and Windows.
"""
