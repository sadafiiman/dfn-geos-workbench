#!/usr/bin/env python3
"""Tests for the SVG fracture-network preview (panel.preview).

Run from the workbench root:  python3 tests/test_preview.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import preview  # noqa: E402

POC_DIR = ROOT / "poc" / "output"

FAMILIES = [
    {"shape": "rect", "distribution": "constant", "constant": 2.0,
     "aspect": 1.0, "probability": 0.5, "trend": 0.0, "plunge": 0.0},
    {"shape": "rect", "distribution": "constant", "constant": 2.0,
     "aspect": 1.0, "probability": 0.5, "trend": 35.0, "plunge": 90.0},
]


class ParamsPreviewTests(unittest.TestCase):
    def test_user_fractures_exact_count(self):
        params = {"domain": [6, 6, 6], "seed": 42,
                  "fractures": [{"shape": "rect", "radii": 0.6,
                                 "translation": [0, 0, 0],
                                 "normal": [0, 0, 1]}]}
        data = preview.fractures_from_params(params)
        self.assertEqual(len(data["fractures"]), 1)
        self.assertFalse(data["sampled"])
        pts = data["fractures"][0]["points"]
        self.assertEqual(len(pts), 4)  # rectangle corners

    def test_families_sampled_to_n_poly(self):
        params = {"domain": [6, 6, 6], "seed": 42, "n_poly": 30,
                  "families": FAMILIES}
        data = preview.fractures_from_params(params)
        self.assertEqual(len(data["fractures"]), 30)
        self.assertTrue(data["sampled"])

    def test_sampling_deterministic(self):
        params = {"domain": [6, 6, 6], "seed": 7, "n_poly": 12,
                  "families": FAMILIES}
        a = preview.fractures_from_params(params)
        b = preview.fractures_from_params(params)
        self.assertEqual(a["fractures"], b["fractures"])

    def test_tpl_radius_respects_bounds(self):
        fam = [{"shape": "ell", "distribution": "tpl", "alpha": 2.5,
                "min_radius": 0.5, "max_radius": 1.0, "probability": 1.0}]
        params = {"domain": [10, 10, 10], "seed": 3, "n_poly": 200,
                  "families": fam}
        data = preview.fractures_from_params(params)
        # the sampled half-length must stay inside [min, max] (ellipse:
        # first coordinate spread around the centre is bounded by the radius)
        for fr in data["fractures"]:
            xs = [p[0] for p in fr["points"]]
            self.assertLessEqual(max(xs) - min(xs), 2 * 1.0 + 1e-9)

    def test_default_two_families_when_nothing_set(self):
        data = preview.fractures_from_params({})
        self.assertEqual(len(data["fractures"]), 24)  # driver default n_poly


class SvgTests(unittest.TestCase):
    def test_three_projections_rendered(self):
        params = {"domain": [8, 6, 4], "seed": 42, "n_poly": 5,
                  "families": FAMILIES}
        html = preview.params_preview_html(params)
        self.assertEqual(html.count("<svg"), 3)
        self.assertIn("XY", html)
        self.assertIn("XZ", html)
        self.assertIn("YZ", html)

    def test_viewbox_matches_domain(self):
        params = {"domain": [8, 6, 4], "seed": 1, "n_poly": 2,
                  "families": FAMILIES}
        svgs = preview.svg_network(preview.fractures_from_params(params))
        self.assertIn('viewBox="-10 -8 20 16"', svgs["xz"])


class ChainEdgesTests(unittest.TestCase):
    def test_open_chain_closed_into_loop(self):
        loops = preview._chain_edges([(0, 1), (1, 2), (2, 3)])
        self.assertEqual(len(loops), 1)
        self.assertEqual(sorted(loops[0]), [0, 1, 2, 3])

    def test_two_disconnected_edges(self):
        loops = preview._chain_edges([(0, 1), (5, 6)])
        self.assertEqual(len(loops), 2)


class CasePreviewTests(unittest.TestCase):
    def test_real_poc_polygons(self):
        if not (POC_DIR / "polys").is_dir():
            self.skipTest("POC dfnWorks output not present")
        data = preview.fractures_from_case(POC_DIR)
        self.assertIsNotNone(data)
        self.assertTrue(data["real"])
        self.assertEqual(data["num_frac"], 5)
        for fr in data["fractures"]:
            self.assertTrue(fr["loops"] or fr["tris"])
        svgs = preview.svg_network(data)
        self.assertGreater(svgs["xy"].count("<polygon"), 0)

    def test_missing_outputs_return_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(preview.fractures_from_case(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
