#!/usr/bin/env python3
"""Converter sanity tests against the real dfnWorks proof-of-concept data.

Run from the workbench root:  python3 tests/test_converters.py
Skips gracefully (with a hint) when the POC outputs are not present.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "conversion"))

import numpy as np  # noqa: E402

from avs_ucd import read_avs_ucd  # noqa: E402

DFM = ROOT / "poc" / "output" / "dfm_mesh"
DFN = ROOT / "poc" / "output"
GEOS_CASE = ROOT / "poc" / "geos_case"

try:
    import vtk  # noqa: E402
    HAVE_VTK = True
except ImportError:
    HAVE_VTK = False


@unittest.skipUnless(DFM.joinpath("dfm_tet_mesh.inp").exists(),
                     "run poc/run_dfm.py first")
class TestAvsUcdReader(unittest.TestCase):
    def test_matrix_mesh_counts(self):
        m = read_avs_ucd(str(DFM / "dfm_tet_mesh.inp"))
        self.assertGreater(m.num_nodes, 0)
        # tetrahedra dominate; LaGriT may add a few pyramids at interfaces
        self.assertTrue(set(m.cell_types) <= {"tet", "pyr", "pri", "hex"},
                        set(m.cell_types))
        self.assertGreater(sum(1 for t in m.cell_types if t == "tet"), 1000)

    def test_facets_merged_fracture_ids(self):
        m = read_avs_ucd(str(DFM / "facets" / "facets_merged.inp"))
        self.assertEqual(set(m.cell_types), {"tri"})
        mats = set(m.cell_materials)
        self.assertTrue(mats.issubset({1, 2, 3, 4, 5}), mats)
        # counts match the per-fracture facet files
        for fid in sorted(mats):
            mf = read_avs_ucd(str(DFM / "facets" / f"facets_f{fid}.inp"))
            self.assertEqual(m.cell_materials.count(fid),
                             sum(1 for t in mf.cell_types if t == "tri"))

    def test_dfn_surface_mesh(self):
        m = read_avs_ucd(str(DFN / "full_mesh.inp"))
        self.assertEqual(set(m.cell_types), {"tri"})


@unittest.skipUnless(GEOS_CASE.joinpath("case.vtm").exists(),
                     "run conversion/dfn_to_geos.py first")
class TestGeosCase(unittest.TestCase):
    def test_vtm_block_names(self):
        mb = vtk.vtkXMLMultiBlockDataReader()
        mb.SetFileName(str(GEOS_CASE / "case.vtm"))
        mb.Update()
        mds = mb.GetOutput()
        names = [mds.GetMetaData(i).Get(mds.NAME())
                 for i in range(mds.GetNumberOfBlocks())]
        self.assertEqual(names, ["main", "fracture"])

    @unittest.skipUnless(HAVE_VTK, "vtk not installed")
    def test_blocks_content(self):
        r = vtk.vtkXMLUnstructuredGridReader()
        r.SetFileName(str(GEOS_CASE / "main.vtu")); r.Update(); main = r.GetOutput()
        self.assertTrue(all(main.GetCell(i).GetCellType() == 10
                            for i in range(main.GetNumberOfCells())))
        self.assertIsNotNone(main.GetPointData().GetArray("GlobalIds"))
        self.assertIsNotNone(main.GetCellData().GetArray("attribute"))

        r2 = vtk.vtkXMLUnstructuredGridReader()
        r2.SetFileName(str(GEOS_CASE / "fracture.vtu")); r2.Update(); frac = r2.GetOutput()
        self.assertTrue(all(frac.GetCell(i).GetCellType() == 5
                            for i in range(frac.GetNumberOfCells())))
        col = frac.GetPointData().GetArray("collocated_nodes")
        self.assertIsNotNone(col)
        mg = main.GetPointData().GetArray("GlobalIds")
        for i in range(col.GetNumberOfTuples()):
            self.assertGreaterEqual(mg.LookupValue(col.GetValue(i)), 0)
        # conforming: coordinates of collocated matrix nodes match
        mism = 0
        for i in range(frac.GetNumberOfPoints()):
            gp = mg.LookupValue(col.GetValue(i))
            if np.linalg.norm(np.array(frac.GetPoint(i))
                              - np.array(main.GetPoint(gp))) > 1e-6:
                mism += 1
        self.assertEqual(mism, 0)

    def test_xml_wellformed_and_geos_fields(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(str(GEOS_CASE / "geos_dfn_fractures.xml")).getroot()
        self.assertEqual(root.tag, "Problem")
        vtk_mesh = root.find("Mesh").find("VTKMesh")
        self.assertEqual(vtk_mesh.get("file"), "case.vtm")
        self.assertIn("fracture", vtk_mesh.get("faceBlocks"))
        self.assertEqual(vtk_mesh.get("useGlobalIds"), "1")
        regions = [e.get("name") for e in root.find("ElementRegions")]
        self.assertIn("Fracture", regions)


@unittest.skipUnless((ROOT / "poc" / "geos_case_edfm" / "geos_dfn_edfm.xml").exists(),
                     "run conversion/poly_to_geos_edfm.py first")
class TestEdfmDeck(unittest.TestCase):
    def test_deck_structure(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(str(ROOT / "poc" / "geos_case_edfm" /
                            "geos_dfn_edfm.xml")).getroot()
        rects = root.find("Geometry").findall("Rectangle")
        self.assertGreaterEqual(len(rects), 1)
        for r in rects:
            for attr in ("origin", "normal", "lengthVector", "widthVector",
                         "dimensions"):
                self.assertTrue(r.get(attr), attr)
        ser = root.find("Solvers").find("EmbeddedSurfaceGenerator")
        self.assertIsNotNone(ser)
        self.assertEqual(ser.get("fractureRegion"), "Fracture")
        # every rectangle is targeted
        targets = [t.strip() for t in
                   ser.get("targetObjects").strip("{} ").split(",")]
        self.assertEqual(sorted(targets),
                         sorted(r.get("name") for r in rects))
        surf = [e for e in root.find("ElementRegions")
                if e.tag == "SurfaceElementRegion"]
        self.assertTrue(surf and surf[0].get("subRegionType") == "embeddedElement")


if __name__ == "__main__":
    unittest.main(verbosity=2)
