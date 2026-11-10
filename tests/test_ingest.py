#!/usr/bin/env python3
"""Upload detection tests (single XML decks, ZIPs, dfnWorks outputs).

Run from the workbench root:  python3 tests/test_ingest.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import ingest  # noqa: E402
from panel.config import Config  # noqa: E402

EDFM_DECK = """<?xml version="1.0" ?>
<Problem>
  <Mesh>
    <InternalMesh name="matrix" elementTypes="{ C3D8 }" xCoords="{ -3, 3 }"
                  yCoords="{ -3, 3 }" zCoords="{ -3, 3 }"
                  nx="{ 20 }" ny="{ 20 }" nz="{ 20 }"
                  cellBlockNames="{ cb1 }"/>
  </Mesh>
</Problem>
"""

FRAGMENT = """<?xml version="1.0" ?>
<Problem>
  <Included><File name="elastic_base.xml"/></Included>
</Problem>
"""


class DeckFixtures(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestSingleDeck(DeckFixtures):
    def test_single_self_contained_xml_is_a_geos_case(self):
        (self.root / "geos_dfn_edfm.xml").write_text(EDFM_DECK)
        info = ingest.detect_action(["geos_dfn_edfm.xml"], True, self.root)
        self.assertEqual(info["action"], "geos")
        self.assertEqual(info["chain"], ["run_geos"])
        self.assertEqual(info["deck"], "geos_dfn_edfm.xml")

    def test_arbitrary_user_deck_is_picked(self):
        (self.root / "my_case.xml").write_text(EDFM_DECK)
        info = ingest.detect_action(["my_case.xml"], True, self.root)
        self.assertEqual(info["action"], "geos")
        self.assertEqual(info["deck"], "my_case.xml")

    def test_deck_with_mesh_files_still_geos(self):
        (self.root / "case.xml").write_text(EDFM_DECK)
        (self.root / "case.vtm").write_bytes(b"<VTKFile/>")
        info = ingest.detect_action(["case.xml", "case.vtm"], True, self.root)
        self.assertEqual(info["action"], "geos")

    def test_fragments_are_not_chosen(self):
        (self.root / "elastic_base.xml").write_text(FRAGMENT)
        (self.root / "good.xml").write_text(EDFM_DECK)
        deck = ingest.pick_deck(["elastic_base.xml", "good.xml"], self.root)
        self.assertEqual(deck, "good.xml")

    def test_generated_edfm_deck_preferred(self):
        (self.root / "other.xml").write_text(EDFM_DECK)
        (self.root / "geos_case_edfm").mkdir()
        (self.root / "geos_case_edfm" / "geos_dfn_edfm.xml").write_text(EDFM_DECK)
        deck = ingest.pick_deck(
            ["other.xml", "geos_case_edfm/geos_dfn_edfm.xml"], self.root)
        self.assertEqual(deck, "geos_case_edfm/geos_dfn_edfm.xml")


class TestOtherUploads(DeckFixtures):
    def test_dfnworks_outputs_win_over_xml(self):
        for name in ("full_mesh.inp", "params.txt", "extra.xml"):
            (self.root / name).write_text("x")
        info = ingest.detect_action(
            ["full_mesh.inp", "params.txt", "extra.xml"], True, self.root)
        self.assertEqual(info["action"], "convert")

    def test_full_pipeline_skips_geos_when_unconfigured(self):
        (self.root / "dfn_driver.py").write_text("print('hi')")
        info = ingest.detect_action(["dfn_driver.py"], False, self.root)
        self.assertEqual(info["action"], "full")
        self.assertEqual(info["chain"], ["dfn_mesh", "convert_to_geos"])

    def test_zip_with_single_deck_extracts_and_detects(self):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("deck/my_deck.xml", EDFM_DECK)
        written = ingest.safe_extract_zip(buf.getvalue(), self.root)
        self.assertEqual(written, ["my_deck.xml"])
        info = ingest.detect_action(written, True, self.root)
        self.assertEqual(info["action"], "geos")
        self.assertEqual(info["deck"], "my_deck.xml")


class TestDeckFileReferences(DeckFixtures):
    """A deck is only runnable when the files it points at are present."""

    TABLE_DECK = """<?xml version="1.0" ?>
<Problem>
  <Mesh>
    <InternalMesh name="m" elementTypes="{ C3D8 }" xCoords="{ 0, 1 }"
                  yCoords="{ 0, 1 }" zCoords="{ 0, 1 }"
                  nx="{ 1 }" ny="{ 1 }" nz="{ 1 }" cellBlockNames="{ cb1 }"/>
  </Mesh>
  <Constitutive>
    <BlackOilFluid name="fluid" phaseNames="{ oil, gas, water }"
      tableFiles="{ pvto.txt, pvtg.txt }"/>
  </Constitutive>
</Problem>
"""

    def _missing(self, name: str) -> list[str]:
        from panel.jobs import _missing_input_files
        return _missing_input_files(self.root / name, self.root)

    def test_table_files_are_checked(self):
        (self.root / "deck.xml").write_text(self.TABLE_DECK)
        self.assertEqual(self._missing("deck.xml"), ["pvtg.txt", "pvto.txt"])
        (self.root / "pvto.txt").write_text("x")
        (self.root / "pvtg.txt").write_text("x")
        self.assertEqual(self._missing("deck.xml"), [])

    def test_mesh_file_is_checked(self):
        (self.root / "deck.xml").write_text(
            '<?xml version="1.0" ?>\n<Problem><Mesh>'
            '<VTKMesh name="m" file="case.vtm"/>'
            "</Mesh></Problem>\n")
        self.assertEqual(self._missing("deck.xml"), ["case.vtm"])
        (self.root / "case.vtm").write_text("<VTKFile/>")
        self.assertEqual(self._missing("deck.xml"), [])

    def test_included_decks_are_checked(self):
        (self.root / "main.xml").write_text(
            '<Problem>\n<Included><File name="base.xml"/></Included>\n</Problem>')
        self.assertEqual(self._missing("main.xml"), ["base.xml"])

    def test_self_contained_deck_needs_nothing(self):
        (self.root / "deck.xml").write_text(self.TABLE_DECK.replace(
            '     tableFiles="{ pvto.txt, pvtg.txt }"', ""))
        self.assertEqual(self._missing("deck.xml"), [])


class TestGeosConfiguration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self, **values):
        c = Config(self.home)
        c._data.update(values)
        return c

    def test_auto_prefers_a_locally_built_image(self):
        c = self._config(geos_backend="auto", geos_exe="",
                         geos_docker_image="")
        c.detect_geos_image = lambda: "dfn-geos:1.1"
        self.assertEqual(c.resolve_backend("geos"), ("docker", "dfn-geos:1.1"))
        self.assertTrue(c.geos_ready())

    def test_docker_backend_without_image_uses_detected(self):
        c = self._config(geos_backend="docker", geos_docker_image="")
        c.detect_geos_image = lambda: "dfn-geos:1.1"
        self.assertEqual(c.resolve_backend("geos"), ("docker", "dfn-geos:1.1"))

    def test_explicit_image_wins(self):
        c = self._config(geos_backend="auto", geos_docker_image="my/geos:v2")
        c.detect_geos_image = lambda: "dfn-geos:1.1"
        self.assertEqual(c.resolve_backend("geos"), ("docker", "my/geos:v2"))

    def test_native_binary_wins_in_auto(self):
        c = self._config(geos_backend="auto", geos_exe="/opt/geos/bin/geosx")
        c.detect_geos_image = lambda: "dfn-geos:1.1"
        self.assertEqual(c.resolve_backend("geos")[0], "native")
        self.assertTrue(c.geos_ready())

    def test_nothing_configured_is_not_ready(self):
        c = self._config(geos_backend="auto", geos_exe="",
                         geos_docker_image="")
        c.detect_geos_image = lambda: ""
        self.assertFalse(c.geos_ready())


if __name__ == "__main__":
    unittest.main(verbosity=2)
