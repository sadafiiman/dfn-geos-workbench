#!/usr/bin/env python3
"""dfnWorks driver generation tests (panel.pipeline.write_driver_script).

The panel's count-based workflow depends on the driver always emitting
``stopCondition=0`` + ``nPoly`` for stochastic families (dfnGen defaults to
p32 mode, which ignores the per-family probabilities), and on pydfnworks'
exact keyword names per radius distribution.

Run from the workbench root:  python3 tests/test_pipeline.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel import dfn_input  # noqa: E402
from panel.pipeline import write_driver_script  # noqa: E402

POC_DAT = (ROOT / "poc" / "output" / "dfnGen_output"
           / "output_dfnGen_input_clean.dat")


class DriverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, params):
        return write_driver_script(self.dir, "case_x", params).read_text()

    def test_default_layout(self):
        code = self._write({})
        self.assertIn("nPoly']['value'] = 24", code)
        self.assertIn("stopCondition']['value'] = 0", code)
        self.assertIn("orientationOption']['value'] = 1", code)
        self.assertIn("boundaryFaces']['value'] = [1, 1, 0, 0, 0, 0]", code)
        self.assertIn("add_fracture_family", code)
        compile(code, "dfn_driver.py", "exec")          # valid python

    def test_families_honour_n_poly_and_distributions(self):
        code = self._write({
            "n_poly": 40, "boundary_faces": [1, 1, 0, 0, 0, 0],
            "families": [
                {"shape": "rect", "distribution": "log_normal",
                 "log_mean": 0.4, "log_std": 0.2, "min_radius": 0.1,
                 "max_radius": 3.0, "probability": 1.0, "trend": 10,
                 "plunge": 80},
                {"shape": "ell", "distribution": "tpl", "alpha": 2.2,
                 "min_radius": 0.1, "max_radius": 5.0, "probability": 0.5},
                {"shape": "rect", "distribution": "exp", "exp_mean": 0.7,
                 "probability": 0.5},
                {"shape": "rect", "distribution": "constant",
                 "constant": 1.2, "probability": 0.5},
            ]})
        self.assertIn("nPoly']['value'] = 40", code)
        self.assertIn("distribution='log_normal'", code)
        self.assertIn("log_mean=0.4, log_std=0.2", code)
        self.assertIn("min_radius=0.1, max_radius=3.0", code)
        self.assertIn("distribution='tpl'", code)
        self.assertIn("alpha=2.2", code)
        self.assertIn("distribution='exp'", code)
        self.assertIn("exp_mean=0.7", code)
        self.assertIn("constant=1.2", code)
        self.assertIn("shape='ell'", code)
        compile(code, "dfn_driver.py", "exec")

    def test_user_fractures_only_skip_stochastic_machinery(self):
        code = self._write({
            "n_poly": 12,
            "fractures": [{"shape": "rect", "radii": 0.6,
                           "translation": [0, 0, 0], "normal": [0, 0, 1],
                           "permeability": 1e-12}]})
        self.assertIn("add_user_fract", code)
        self.assertNotIn("nPoly", code)                 # no stochastic families
        self.assertNotIn("add_fracture_family", code)

    def test_user_fractures_plus_families(self):
        code = self._write({
            "n_poly": 9,
            "fractures": [{"shape": "rect", "radii": 0.6,
                           "translation": [0, 0, 0], "normal": [0, 0, 1]}],
            "families": [{"shape": "rect", "distribution": "constant",
                          "constant": 2.0, "probability": 1.0}]})
        self.assertIn("add_user_fract", code)
        self.assertIn("nPoly']['value'] = 9", code)
        self.assertIn("add_fracture_family", code)

    def test_parse_then_generate_matches_poc_deck(self):
        if not POC_DAT.exists():
            self.skipTest("POC dfnGen output not present")
        parsed = dfn_input.parse_dfn_dat(POC_DAT.read_text())
        params = {"domain": [6.0, 6.0, 6.0], "h": 0.35, "seed": 42, "ncpu": 4}
        params.update(parsed["params"])
        params["families"] = parsed["families"]
        code = self._write(params)
        self.assertIn("nPoly']['value'] = 24", code)
        self.assertIn("constant=2.0", code)
        self.assertIn("trend=35.0, plunge=90.0", code)
        self.assertIn("probability=0.5", code)
        self.assertIn("beta_distribution=1", code)
        compile(code, "dfn_driver.py", "exec")


class DriverMatrixTests(unittest.TestCase):
    """Systematic coverage of every editable DFN input -> driver output."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, params):
        return write_driver_script(self.dir, "case_x", params).read_text()

    def test_full_shape_distribution_kappa_beta_matrix(self):
        """2 shapes x 4 distributions x (kappa blank|set) x (beta const|value)."""
        for shape in ("rect", "ell"):
            for dist, size_key, size in (
                    ("constant", "constant", 2.0),
                    ("log_normal", "log_mean", 0.4),
                    ("tpl", "alpha", 2.5),
                    ("exp", "exp_mean", 1.2)):
                for kappa in (None, 15.0):
                    for bd, beta in ((0, None), (1, 0.7)):
                        with self.subTest(shape=shape, dist=dist,
                                          kappa=kappa, bd=bd):
                            fam = {"shape": shape, "distribution": dist,
                                   size_key: size, "probability": 1.0,
                                   "trend": 10, "plunge": 80,
                                   "beta_distribution": bd,
                                   "beta": beta if bd else 0.0}
                            if kappa is not None:
                                fam["kappa"] = kappa
                            code = self._write({"n_poly": 5,
                                                "families": [fam]})
                            compile(code, "dfn_driver.py", "exec")
                            self.assertIn(f"shape='{shape}'", code)
                            self.assertIn(f"distribution='{dist}'", code)
                            self.assertIn("nPoly']['value'] = 5", code)
                            self.assertIn("stopCondition']['value'] = 0", code)
                            self.assertIn({2.0: "constant=2.0",
                                           0.4: "log_mean=0.4, log_std=0.5",
                                           2.5: "alpha=2.5",
                                           1.2: "exp_mean=1.2"}[size], code)
                            self.assertIn(
                                "beta_distribution=%d, beta=%s"
                                % (bd, "0.7" if bd else "0.0"), code)
                            self.assertIn("kappa=%s"
                                          % ("15.0" if kappa is not None
                                             else "20.0"), code)

    def test_missing_kappa_defaults_to_20_per_family(self):
        """Regression: dfnGen aborts when rkappa has fewer entries than
        families ('rkappa has defined 2 value(s) but there are 3 families')."""
        code = self._write({"n_poly": 10, "families": [
            {"shape": "rect", "distribution": "constant", "constant": 2.0,
             "kappa": 20.0, "probability": 1.0, "trend": 0.0, "plunge": 0.0},
            {"shape": "rect", "distribution": "constant", "constant": 2.0,
             "kappa": 20.0, "probability": 1.0, "trend": 35.0, "plunge": 90.0},
            {"shape": "rect", "distribution": "constant", "constant": 1.0,
             "probability": 1.0}]})          # kappa left blank
        self.assertEqual(code.count("kappa=20.0"), 3)
        compile(code, "dfn_driver.py", "exec")

    def test_size_bounds_per_distribution(self):
        for dist, key in (("log_normal", "log_mean"), ("tpl", "alpha"),
                          ("exp", "exp_mean")):
            with self.subTest(dist=dist):
                fam = {"shape": "rect", "distribution": dist, key: 0.5,
                       "min_radius": 0.1, "max_radius": 4.0,
                       "probability": 1.0}
                code = self._write({"n_poly": 3, "families": [fam]})
                self.assertIn("min_radius=0.1, max_radius=4.0", code)
        # 'constant' has no bounds in dfnWorks — they must not be emitted
        fam = {"shape": "rect", "distribution": "constant", "constant": 2.0,
               "min_radius": 0.1, "max_radius": 4.0, "probability": 1.0}
        code = self._write({"n_poly": 3, "families": [fam]})
        self.assertNotIn("min_radius", code)

    def test_n_poly_and_stochastic_machinery_variants(self):
        # default of 24 when unset
        self.assertIn("nPoly']['value'] = 24", self._write({}))
        # user fractures only: no stochastic machinery at all (even nPoly=0)
        code = self._write({
            "n_poly": 0,
            "fractures": [{"shape": "rect", "radii": 0.5,
                           "translation": [0, 0, 0], "normal": [0, 0, 1]}]})
        self.assertNotIn("nPoly", code)
        self.assertNotIn("orientationOption", code)
        self.assertNotIn("boundaryFaces", code)
        # custom orientation option is honoured
        code = self._write({
            "n_poly": 4, "orientation_option": 3,
            "families": [{"shape": "rect", "distribution": "constant",
                          "constant": 1.0}]})
        self.assertIn("orientationOption']['value'] = 3", code)

    def test_boundary_mesh_and_env_flags(self):
        fam = {"shape": "rect", "distribution": "constant", "constant": 1.0,
               "probability": 1.0}
        code = self._write({"n_poly": 2, "families": [fam],
                            "boundary_faces": [0, 1, 1, 0, 1, 1],
                            "ignore_boundary_faces": False,
                            "mesh_dfm": False, "seed": 7, "ncpu": 2,
                            "domain": [10.0, 8.0, 6.0], "h": 0.25})
        self.assertIn("boundaryFaces']['value'] = [0, 1, 1, 0, 1, 1]", code)
        self.assertIn('ignoreBoundaryFaces"]["value"] = 0', code)
        self.assertNotIn("DFN.mesh_dfm", code)
        self.assertIn('seed"]["value"] = 7', code)
        self.assertIn("ncpu=2", code)
        self.assertIn('domainSize"]["value"] = [10.0, 8.0, 6.0]', code)
        self.assertIn('h"]["value"] = 0.25', code)
        # DFM meshing back on -> the mesh_dfm call is emitted
        code2 = self._write({"n_poly": 2, "families": [fam],
                             "mesh_dfm": True, "dfm_allowed_percentage": 3})
        self.assertIn("DFN.mesh_dfm(allowed_percentage=3.0", code2)

    def test_hydraulic_params_propagate(self):
        fam = {"shape": "rect", "distribution": "constant", "constant": 1.0,
               "probability": 1.0, "hy": {"alpha": 2e-12, "beta": 1.5}}
        code = self._write({"n_poly": 2, "families": [fam]})
        self.assertIn("'alpha': 2e-12", code)
        self.assertIn("'beta': 1.5", code)


if __name__ == "__main__":
    unittest.main()
