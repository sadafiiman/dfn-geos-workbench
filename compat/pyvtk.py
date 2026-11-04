"""Minimal pyvtk compatibility shim.

pydfnworks uses pyvtk in ``mesh_dfn_helper.inp2vtk_python`` to dump the AVS
``full_mesh.inp`` mesh as a legacy VTK file::

    vtk = pv.VtkData(pv.UnstructuredGrid(coord, tetra=..., triangle=...),
                     'Unstructured pflotran grid')
    vtk.tofile(vtk_file)

This shim writes the same legacy VTK ASCII output directly (no dependencies).
"""


class UnstructuredGrid:
    def __init__(self, points, tetra=None, triangle=None, quad=None):
        self.points = points
        self.cells = []
        # (vtk_cell_type, node_list) -- 10 = VTK_TETRA, 5 = VTK_TRIANGLE
        for cell in tetra or []:
            self.cells.append((10, list(cell)))
        for cell in triangle or []:
            self.cells.append((5, list(cell)))
        for cell in quad or []:
            self.cells.append((9, list(cell)))


class VtkData:
    def __init__(self, ugrid, title="dfn mesh"):
        self.ugrid = ugrid
        self.title = title

    def tofile(self, filename, binary=False):  # noqa: ARG002
        pts = self.ugrid.points
        cells = self.ugrid.cells
        total_size = sum(1 + len(c[1]) for c in cells)
        with open(filename, "w") as f:
            f.write("# vtk DataFile Version 2.0\n")
            f.write(f"{self.title}\n")
            f.write("ASCII\n")
            f.write("DATASET UNSTRUCTURED_GRID\n")
            f.write(f"POINTS {len(pts)} float\n")
            for p in pts:
                f.write(f"{p[0]:.6e} {p[1]:.6e} {p[2]:.6e}\n")
            f.write(f"\nCELLS {len(cells)} {total_size}\n")
            for ctype, nodes in cells:
                f.write(f"{len(nodes)} " + " ".join(str(int(n)) for n in nodes) + "\n")
            f.write(f"\nCELL_TYPES {len(cells)}\n")
            for ctype, _ in cells:
                f.write(f"{ctype}\n")
