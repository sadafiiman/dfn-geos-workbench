#!/usr/bin/env python3
"""Tests for the dfnGen .dat input parser (panel.dfn_input).

Run from the workbench root:  python3 tests/test_dfn_input.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import dfn_input  # noqa: E402

POC_DAT = (ROOT / "poc" / "output" / "dfnGen_output"
           / "output_dfnGen_input_clean.dat")


class PocDeckTests(unittest.TestCase):
    """The parser must reproduce the real dfnGen deck from the POC run."""

    def setUp(self):
        if not POC_DAT.exists():
            self.skipTest("POC dfnGen output not present")
        self.parsed = dfn_input.parse_dfn_dat(POC_DAT.read_text())

    def test_globals(self):
        p = self.parsed["params"]
        self.assertEqual(p["domain"], [6.0, 6.0, 6.0])
        self.assertEqual(p["h"], 0.35)
        self.assertEqual(p["seed"], 6969420)
        self.assertEqual(p["n_poly"], 24)
        self.assertEqual(p["boundary_faces"], [1, 1, 0, 0, 0, 0])
        self.assertIs(p["ignore_boundary_faces"], False)
        self.assertEqual(p["orientation_option"], 1)

    def test_two_constant_rect_families(self):
        fams = self.parsed["families"]
        self.assertEqual(len(fams), 2)
        for fam in fams:
            self.assertEqual(fam["shape"], "rect")
            self.assertEqual(fam["distribution"], "constant")
            self.assertEqual(fam["constant"], 2.0)
            self.assertEqual(fam["aspect"], 1.0)
            self.assertEqual(fam["beta_distribution"], 1)
            self.assertEqual(fam["probability"], 0.5)
        self.assertEqual(fams[0]["trend"], 0.0)
        self.assertEqual(fams[0]["plunge"], 0.0)
        self.assertEqual(fams[1]["trend"], 35.0)
        self.assertEqual(fams[1]["plunge"], 90.0)
        self.assertEqual(fams[0]["kappa"], 20.0)

    def test_unmapped_keeps_unmodelled_keys(self):
        unmapped = self.parsed["unmapped"]
        self.assertIn("keepOnlyLargestCluster", unmapped)
        self.assertIn("insertUserRectanglesFirst", unmapped)
        for consumed in ("stopCondition", "nPoly", "domainSize", "h", "seed",
                         "rconst", "rtrend", "rplunge", "famProb"):
            self.assertNotIn(consumed, unmapped)
        self.assertEqual(unmapped["keepOnlyLargestCluster"], "1")
        self.assertEqual(unmapped["layers"], "{}")

    def test_looks_like_dfn_dat(self):
        self.assertTrue(dfn_input.looks_like_dfn_dat(self.parsed))


class SyntheticDeckTests(unittest.TestCase):
    def _parse(self, text):
        return dfn_input.parse_dfn_dat(text)

    def test_comments_and_curlies(self):
        parsed = self._parse(
            "// header comment\n"
            "domainSize: {10.0, 20.0, 5.0}  /* inline */\n"
            "h: 0.5\n"
            "seed: 7\n"
            "stopCondition: 0\n"
            "nPoly: 8\n")
        self.assertEqual(parsed["params"]["domain"], [10.0, 20.0, 5.0])
        self.assertEqual(parsed["params"]["h"], 0.5)
        self.assertEqual(parsed["params"]["seed"], 7)
        self.assertEqual(parsed["params"]["n_poly"], 8)

    def test_distribution_codes_map_to_driver_names(self):
        text = (
            "stopCondition: 0\nnPoly: 12\ndomainSize: {6.0,6.0,6.0}\n"
            "famProb: {0.25,0.25,0.25,0.25}\nnFracFam: 4\n"
            "nFamEll: 2\nnFamRect: 2\n"
            "edistr: {1,3}\neaspect: {1.5,2.0}\n"
            "eLogMean: {0.4,0.0}\nesd: {0.2,0.0}\n"
            "eLogMin: {0.1,0.1}\neLogMax: {3.0,3.0}\n"
            "eExpMean: {0.0,0.8}\neExpMin: {0.1,0.1}\neExpMax: {4.0,4.0}\n"
            "rdistr: {2,4}\nraspect: {1.0,1.0}\n"
            "ralpha: {2.4,0.0}\nrmin: {0.05,0.0}\nrmax: {5.0,0.0}\n"
            "rconst: {0.0,1.2}\n"
            "rtrend: {10.0,0.0}\nrplunge: {80.0,0.0}\n")
        fams = self._parse(text)["families"]
        self.assertEqual([f["shape"] for f in fams],
                         ["ell", "ell", "rect", "rect"])
        self.assertEqual(fams[0]["distribution"], "log_normal")
        self.assertEqual(fams[0]["log_mean"], 0.4)
        self.assertEqual(fams[0]["log_std"], 0.2)
        self.assertEqual(fams[0]["min_radius"], 0.1)
        self.assertEqual(fams[1]["distribution"], "exp")
        self.assertEqual(fams[1]["exp_mean"], 0.8)
        self.assertEqual(fams[2]["distribution"], "tpl")
        self.assertEqual(fams[2]["alpha"], 2.4)
        self.assertEqual(fams[2]["min_radius"], 0.05)
        self.assertEqual(fams[2]["max_radius"], 5.0)
        self.assertEqual(fams[3]["distribution"], "constant")
        self.assertEqual(fams[3]["constant"], 1.2)
        # famProb indexed by definition order (ellipses first)
        self.assertEqual([f["probability"] for f in fams],
                         [0.25, 0.25, 0.25, 0.25])

    def test_p32_stop_condition_reported(self):
        parsed = self._parse(
            "stopCondition: 1\nnPoly: 0\ndomainSize: {6.0,6.0,6.0}\n"
            "h: 0.35\nseed: 1\n")
        self.assertNotIn("n_poly", parsed["params"])
        self.assertTrue(any("stopCondition" in n for n in parsed["notes"]))

    def test_not_a_dfn_deck(self):
        parsed = dfn_input.parse_dfn_dat(
            "intersection_list: {1,2}\n")
        self.assertFalse(dfn_input.looks_like_dfn_dat(parsed))
        self.assertEqual(parsed["families"], [])


if __name__ == "__main__":
    unittest.main()
