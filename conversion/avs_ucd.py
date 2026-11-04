"""Reader for AVS/UCD ``.inp`` unstructured mesh files (LaGriT output).

LaGriT writes AVS/UCD files with element lines of the form::

    <cell-id> <material> <tri|tet|quad|hex|...> <n1> <n2> ... <nk>

Some AVS writers omit the element-type token; both variants are handled.
Node lines are ``<node-id> <x> <y> <z>``; node/element ids are 1-based.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# LaGriT/AVS cell-type tokens -> (n_nodes, vtk_cell_type)
CELL_TOKENS = {
    "pt": (1, 1),
    "line": (2, 3),
    "tri": (3, 5),          # VTK_TRIANGLE
    "quad": (4, 9),         # VTK_QUAD
    "tet": (4, 10),         # VTK_TETRA
    "hex": (8, 12),         # VTK_HEXAHEDRON
    "pri": (6, 13),         # VTK_WEDGE
    "pyr": (5, 14),         # VTK_PYRAMID
}


@dataclass
class UcdMesh:
    """Parsed AVS/UCD mesh."""
    points: np.ndarray                    # (N, 3) float64, 0-based indexing
    cell_types: list                      # ['tri', 'tet', ...]
    cell_nodes: list                      # list of 0-based node index lists
    cell_materials: list                  # material/attribute id per cell
    node_ids: list = field(default_factory=list)   # original 1-based ids
    cell_ids: list = field(default_factory=list)   # original 1-based ids

    @property
    def num_nodes(self) -> int:
        return len(self.points)

    def cells_of_type(self, ctype: str):
        """Yield (local_index, nodes, material) for all cells of a type."""
        for i, (t, nodes, mat) in enumerate(zip(self.cell_types, self.cell_nodes,
                                                self.cell_materials)):
            if t == ctype:
                yield i, nodes, mat


def read_avs_ucd(path: str) -> UcdMesh:
    """Read an AVS/UCD ``.inp`` file written by LaGriT or a standard writer."""
    nodes = {}
    order = []
    cell_types, cell_nodes, cell_materials, cell_ids = [], [], [], []

    with open(path) as fh:
        header = fh.readline().split()
        if len(header) >= 2:
            n_nodes_declared, n_cells_declared = int(header[0]), int(header[1])
        else:  # pragma: no cover - defensive
            n_nodes_declared, n_cells_declared = -1, -1

        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            tok = line.split()
            if len(tok) < 4:
                continue
            try:
                nid = int(tok[0])
            except ValueError:
                continue
            # element line? (a cell-type token appears among the first fields)
            token = None
            for cand in tok[1:4]:
                if cand.lower() in CELL_TOKENS:
                    token = cand.lower()
                    break
            if token is not None:
                # LaGriT layout: <cell-id> <material> <token> <n1> ...
                before = tok[1:tok.index(token) if token in tok else 2]
                material = int(before[-1]) if before else 0
                rest = tok[tok.index(token) + 1:]
            elif _is_float(tok[1]) and _is_float(tok[2]) and _is_float(tok[3]) \
                    and len(tok) in (4, 5):
                # node line: id x y z [optional extra]
                if nid not in nodes:
                    nodes[nid] = (float(tok[1]), float(tok[2]), float(tok[3]))
                    order.append(nid)
                continue
            else:
                # standard AVS layout: <cell-id> <material> <n1> ... <nk>
                try:
                    material = int(tok[1])
                except ValueError:
                    continue  # attribute/data row, not an element
                rest = tok[2:]
                guess = {3: "tri", 4: "tet", 8: "hex", 6: "pri", 5: "pyr"}
                token = guess.get(len(rest), None)
                if token is None:
                    continue
                nnodes_g = CELL_TOKENS[token][0]
                try:
                    ids_guess = [int(v) for v in rest[:nnodes_g]]
                except ValueError:
                    continue
                # guard: a real element references *known, distinct* nodes;
                # this rejects trailing attribute rows misread as elements.
                if len(set(ids_guess)) != nnodes_g or \
                        any(i not in nodes for i in ids_guess):
                    continue
            nnodes, _vtk = CELL_TOKENS[token]
            if len(rest) < nnodes:
                continue
            try:
                ids = [int(v) for v in rest[:nnodes]]  # original 1-based ids
            except ValueError:
                continue
            cell_types.append(token)
            cell_nodes.append(ids)
            cell_materials.append(material)
            cell_ids.append(nid)

    pts = np.array([nodes[i] for i in order], dtype=np.float64)
    remap = {nid: k for k, nid in enumerate(order)}
    cell_nodes = [[remap[i] for i in cell] for cell in cell_nodes]
    return UcdMesh(points=pts,
                   cell_types=cell_types,
                   cell_nodes=cell_nodes,
                   cell_materials=cell_materials,
                   node_ids=order,
                   cell_ids=cell_ids)


def _is_float(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False
