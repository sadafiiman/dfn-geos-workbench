"""Minimal VTK XML writers (VTU / VTP / VTM) using only the standard library.

GEOS reads meshes through the VTK library, so any file that a stock VTK
reader accepts is GEOS-compatible.  These writers emit ASCII VTK XML
(``version="0.1"``) that ``vtkXMLUnstructuredGridReader`` /
``vtkXMLPolyDataReader`` / ``vtkXMLMultiBlockDataReader`` parse, and therefore
the same pipeline GEOS's ``VTKMeshGenerator`` uses.

Cell-type reference (VTK):
    vertex=1, line=3, triangle=5, quad=9, tetra=10, hexahedron=12,
    wedge=13, pyramid=14
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path

import numpy as np


def _fmt_array(values: np.ndarray) -> str:
    """Format a numpy array as a compact ASCII payload."""
    if values.dtype.kind in "iu":
        return " ".join(str(int(v)) for v in np.ravel(values))
    return " ".join(f"{float(v):.10g}" for v in np.ravel(values))


def _data_array(name: str, values: np.ndarray, num_components: int = 1,
                dtype: str | None = None) -> str:
    values = np.asarray(values)
    if dtype is None:
        dtype = {np.dtype(np.int8): "Int8", np.dtype(np.int32): "Int32",
                 np.dtype(np.int64): "Int64", np.dtype(np.uint8): "UInt8",
                 np.dtype(np.float32): "Float32",
                 np.dtype(np.float64): "Float64"}.get(values.dtype,
                                                      "Float64")
    ncomp = f' NumberOfComponents="{num_components}"' if num_components > 1 else ""
    return (f'        <DataArray type="{dtype}" Name="{name}"{ncomp} '
            f'format="ascii">\n          {_fmt_array(values)}\n'
            f"        </DataArray>\n")


def write_vtu(path, points, cell_blocks, point_data=None, cell_data=None,
              binary_float32: bool = False) -> None:
    """Write an ``.vtu`` UnstructuredGrid.

    Parameters
    ----------
    path : str or Path
        Output file name.
    points : (N,3) array of node coordinates.
    cell_blocks : list of tuples ``(vtk_cell_type, connectivity_list)`` where
        ``connectivity_list`` is a flat list of 0-based node indices grouped
        by cell (all cells in one block have the same node count).
    point_data, cell_data : dict name -> 1D/2D array (per point / per cell).
    binary_float32 : write point coordinates as Float32 appended-binary to
        keep file sizes small (ascii otherwise).
    """
    points = np.asarray(points, dtype=np.float64)
    conn, offsets, types = [], [], []
    for vtk_type, nodes in cell_blocks:
        nodes = np.asarray(nodes, dtype=np.int64).ravel()
        n_per = _nodes_per_cell(vtk_type)
        if n_per and nodes.size % n_per:
            raise ValueError(f"connectivity size {nodes.size} not a multiple "
                             f"of {n_per} for cell type {vtk_type}")
        ncells = nodes.size // (n_per or 1)
        conn.extend(nodes.tolist())
        for k in range(ncells):
            offsets.append(len(conn) - nodes.size + (k + 1) * n_per)
        types.extend([vtk_type] * ncells)

    conn_arr = np.asarray(conn, dtype=np.int64)
    offsets_arr = np.asarray(offsets, dtype=np.int64)
    types_arr = np.asarray(types, dtype=np.uint8)

    point_data = point_data or {}
    cell_data = cell_data or {}

    if binary_float32:
        # VTK inline "binary" format = base64 of [UInt32 length header][data]
        payload = points.astype(np.float32).tobytes()
        b64 = base64.b64encode(
            struct.pack("<I", len(payload)) + payload).decode("ascii")
        points_block = (f'      <Points>\n        <DataArray type="Float32" '
                        f'Name="Points" NumberOfComponents="3" format="binary">'
                        f"\n          {b64}\n        </DataArray>\n"
                        f"      </Points>\n")
    else:
        points_block = (f'      <Points>\n'
                        f'        <DataArray type="Float64" Name="Points" '
                        f'NumberOfComponents="3" format="ascii">\n'
                        f"          {_fmt_array(points)}\n"
                        f"        </DataArray>\n      </Points>\n")

    pd_block = "      <PointData>\n"
    for name, arr in point_data.items():
        arr = np.asarray(arr)
        ncomp = arr.shape[1] if arr.ndim == 2 else 1
        pd_block += _data_array(name, arr, ncomp)
    pd_block += "      </PointData>\n"

    cd_block = "      <CellData>\n"
    for name, arr in cell_data.items():
        arr = np.asarray(arr)
        ncomp = arr.shape[1] if arr.ndim == 2 else 1
        cd_block += _data_array(name, arr, ncomp)
    cd_block += "      </CellData>\n"

    xml = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="UnstructuredGrid" version="0.1" '
        'byte_order="LittleEndian">\n'
        "  <UnstructuredGrid>\n"
        f'    <Piece NumberOfPoints="{points.shape[0]}" '
        f'NumberOfCells="{len(types)}">\n'
        + pd_block + cd_block + points_block +
        "      <Cells>\n" +
        _data_array("connectivity", conn_arr) +
        _data_array("offsets", offsets_arr) +
        _data_array("types", types_arr) +
        "      </Cells>\n"
        "    </Piece>\n"
        "  </UnstructuredGrid>\n"
        "</VTKFile>\n"
    )
    Path(path).write_text(xml)


def write_vtp(path, points, triangles) -> None:
    """Write a ``.vtp`` PolyData file containing a triangle surface."""
    points = np.asarray(points, dtype=np.float64)
    tri = np.asarray(triangles, dtype=np.int64).ravel()
    n = len(tri) // 3
    xml = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian">\n'
        "  <PolyData>\n"
        f'    <Piece NumberOfPoints="{points.shape[0]}" NumberOfPolys="{n}">\n'
        "      <Points>\n"
        '        <DataArray type="Float64" Name="Points" '
        'NumberOfComponents="3" format="ascii">\n'
        f"          {_fmt_array(points)}\n"
        "        </DataArray>\n"
        "      </Points>\n"
        "      <Polys>\n"
        f'        <DataArray type="Int64" Name="connectivity" '
        f'format="ascii">\n          {_fmt_array(tri)}\n        </DataArray>\n'
        f'        <DataArray type="Int64" Name="offsets" format="ascii">\n'
        f"          {' '.join(str(3 * (i + 1)) for i in range(n))}\n"
        "        </DataArray>\n"
        "      </Polys>\n"
        "    </Piece>\n"
        "  </PolyData>\n"
        "</VTKFile>\n"
    )
    Path(path).write_text(xml)


def write_vtm(path, blocks) -> None:
    """Write a ``.vtm`` multi-block dataset.

    Parameters
    ----------
    blocks : list of ``(name, file_name)`` pairs.  GEOS looks up the main
        volume block by name (default ``main``) and face blocks through the
        ``faceBlocks`` attribute of ``<VTKMesh>``.
    """
    entries = "\n".join(f'        <DataSet name="{n}" file="{f}"/>'
                        for n, f in blocks)
    xml = (
        '<?xml version="1.0"?>\n'
        '<VTKFile type="vtkMultiBlockDataSet" version="1.0">\n'
        "  <vtkMultiBlockDataSet>\n"
        f"{entries}\n"
        "  </vtkMultiBlockDataSet>\n"
        "</VTKFile>\n"
    )
    Path(path).write_text(xml)


def _nodes_per_cell(vtk_type: int) -> int:
    return {1: 1, 3: 2, 5: 3, 9: 4, 10: 4, 12: 8, 13: 6, 14: 5}.get(vtk_type, 0)
