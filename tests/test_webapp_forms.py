#!/usr/bin/env python3
"""Edit-DFN form parsing tests (panel.webapp form helpers).

Covers the whole Edit-DFN form surface: number/vector parsing and error
reporting, per-distribution size keys, bounds, kappa, beta, row deletion,
nPoly validation (blank = default 24, 0 rejected with stochastic families),
boundary-faces parsing, import-leftover cleanup and the shared defaults.

Run from the workbench root:  python3 tests/test_webapp_forms.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panel.pipeline import DEFAULT_FAMILIES, write_driver_script  # noqa: E402
from panel.webapp import (default_params, _family_from_form,  # noqa: E402
                          _params_from_form, _uf_from_form)


def _fam_form(i=0, **kw):
    """Build a form dict with the fam<i>_ fields for one family row."""
    base = {f"fam{i}_shape": "rect", f"fam{i}_dist": "constant",
            f"fam{i}_size": "2.0", f"fam{i}_prob": "1.0",
            f"fam{i}_trend": "0", f"fam{i}_plunge": "0"}
    base.update({f"fam{i}_{k}": v for k, v in kw.items()})
    return base


def _uf_form(i=0, **kw):
    base = {f"uf{i}_shape": "rect", f"uf{i}_radii": "0.5",
            f"uf{i}_ctr": "0,0,0", f"uf{i}_nrm": "0,0,1"}
    base.update({f"uf{i}_{k}": v for k, v in kw.items()})
    return base


class FamilyRowTests(unittest.TestCase):
    def test_every_distribution_maps_its_size_key(self):
        for dist, key in (("constant", "constant"),
                          ("log_normal", "log_mean"), ("tpl", "alpha"),
                          ("exp", "exp_mean")):
            with self.subTest(dist=dist):
                fam = _family_from_form(
                    _fam_form(dist=dist, size="1.5"), 0, [])
                self.assertEqual(fam[key], 1.5)
                self.assertEqual(fam["distribution"], dist)

    def test_log_normal_sd_and_bounds(self):
        fam = _family_from_form(_fam_form(dist="log_normal", size="0.4",
                                          sd="0.2", min="0.1", max="3"),
                                0, [])
        self.assertEqual(fam["log_std"], 0.2)
        self.assertEqual(fam["min_radius"], 0.1)
        self.assertEqual(fam["max_radius"], 3.0)

    def test_constant_ignores_bounds(self):
        fam = _family_from_form(_fam_form(min="0.1", max="9"), 0, [])
        self.assertNotIn("min_radius", fam)
        self.assertNotIn("max_radius", fam)

    def test_kappa_blank_stays_absent(self):
        fam = _family_from_form(_fam_form(), 0, [])
        self.assertNotIn("kappa", fam)
        fam = _family_from_form(_fam_form(kappa="15"), 0, [])
        self.assertEqual(fam["kappa"], 15.0)

    def test_beta_distribution_flag(self):
        fam = _family_from_form(_fam_form(bd="on", beta="0.7"), 0, [])
        self.assertEqual(fam["beta_distribution"], 1)
        self.assertEqual(fam["beta"], 0.7)
        fam = _family_from_form(_fam_form(), 0, [])
        self.assertEqual(fam["beta_distribution"], 0)
        self.assertEqual(fam["beta"], 0.0)

    def test_invalid_numbers_reported(self):
        errs = []
        _family_from_form(_fam_form(size="abc"), 0, errs)
        self.assertTrue(any("not a number" in e for e in errs))


class UserFractureRowTests(unittest.TestCase):
    def test_untouched_row_is_skipped(self):
        self.assertIsNone(_uf_from_form({"uf0_shape": "rect"}, 0, []))

    def test_full_row(self):
        uf = _uf_from_form(_uf_form(shape="ell", radii="0.6", aspect="2",
                                    ctr="0.1, 0.2, 0.3", nrm="0, 0, 1",
                                    perm="1e-13"), 0, [])
        self.assertEqual(uf["shape"], "ell")
        self.assertEqual(uf["radii"], 0.6)
        self.assertEqual(uf["aspect_ratio"], 2.0)
        self.assertEqual(uf["translation"], [0.1, 0.2, 0.3])
        self.assertEqual(uf["normal"], [0.0, 0.0, 1.0])
        self.assertEqual(uf["permeability"], 1e-13)

    def test_bad_vectors_reported(self):
        errs = []
        _uf_from_form(_uf_form(ctr="1,2"), 0, errs)
        self.assertTrue(any("need 3 numbers" in e for e in errs))


class ParamsFormTests(unittest.TestCase):
    def test_full_valid_form(self):
        form = {"dx": "10", "dy": "8", "dz": "6", "h": "0.25", "seed": "7",
                "ncpu": "2", "n_poly": "10",
                "boundary_faces": "1, 1, 0, 0, 0, 0",
                "ignore_boundary_faces": "on", "mesh_dfm": "on",
                "fam_count": "1", "uf_count": "1"}
        form.update(_fam_form(dist="tpl", size="2.2", min="0.1", max="5",
                              prob="1", trend="0", plunge="0"))
        form.update(_uf_form(radii="0.6", ctr="0,0,0", nrm="0,0,1"))
        p, errs = _params_from_form(form, {})
        self.assertEqual(errs, [])
        self.assertEqual(p["domain"], [10.0, 8.0, 6.0])
        self.assertEqual(p["h"], 0.25)
        self.assertEqual(p["seed"], 7)
        self.assertEqual(p["ncpu"], 2)
        self.assertEqual(p["n_poly"], 10)
        self.assertEqual(p["boundary_faces"], [1, 1, 0, 0, 0, 0])
        self.assertTrue(p["ignore_boundary_faces"])
        self.assertTrue(p["mesh_dfm"])
        self.assertEqual(len(p["families"]), 1)
        self.assertEqual(p["families"][0]["alpha"], 2.2)
        self.assertEqual(len(p["fractures"]), 1)
        self.assertEqual(p["fractures"][0]["radii"], 0.6)

    def test_blank_n_poly_means_default_24(self):
        p, errs = _params_from_form({"n_poly": "", "fam_count": "0",
                                     "uf_count": "0"}, {})
        self.assertEqual(errs, [])
        self.assertEqual(p["n_poly"], 24)

    def test_n_poly_zero_rejected_with_stochastic_families(self):
        form = {"n_poly": "0", "fam_count": "1", "uf_count": "0"}
        form.update(_fam_form(size="2"))
        p, errs = _params_from_form(form, {})
        self.assertTrue(any("at least 1" in e for e in errs))
        self.assertNotIn("n_poly", p)

    def test_n_poly_zero_allowed_with_user_fractures_only(self):
        form = {"n_poly": "0", "fam_count": "0", "uf_count": "1"}
        form.update(_uf_form())
        p, errs = _params_from_form(form, {})
        self.assertEqual(errs, [])
        self.assertEqual(p["n_poly"], 0)

    def test_negative_n_poly_rejected(self):
        form = {"n_poly": "-3", "fam_count": "0", "uf_count": "0"}
        _, errs = _params_from_form(form, {})
        self.assertTrue(any("at least 1" in e for e in errs))

    def test_bad_boundary_faces(self):
        form = {"n_poly": "5", "boundary_faces": "1,2", "fam_count": "0",
                "uf_count": "0"}
        _, errs = _params_from_form(form, {})
        self.assertTrue(any("six 0/1 values" in e for e in errs))

    def test_delete_rows_via_checkboxes(self):
        form = {"n_poly": "5", "fam_count": "2", "uf_count": "2",
                "fam0_del": "on", "uf0_del": "on"}
        form.update(_fam_form(i=1, size="3.0"))
        form.update(_uf_form(i=1, radii="0.9"))
        p, errs = _params_from_form(form, {})
        self.assertEqual(errs, [])
        self.assertEqual(len(p["families"]), 1)
        self.assertEqual(p["families"][0]["constant"], 3.0)
        self.assertEqual(len(p["fractures"]), 1)
        self.assertEqual(p["fractures"][0]["radii"], 0.9)

    def test_save_drops_dfn_import_leftovers(self):
        base = {"dfn_unmapped": {"someKey": "1"}, "dfn_notes": ["note"],
                "dfn_source": "deck.dat", "h": 0.4}
        form = {"n_poly": "5", "fam_count": "0", "uf_count": "0"}
        p, errs = _params_from_form(form, base)
        self.assertEqual(errs, [])
        for k in ("dfn_unmapped", "dfn_notes", "dfn_source"):
            self.assertNotIn(k, p)
        self.assertEqual(p["h"], 0.4)          # non-import keys survive

    def test_invalid_numbers_reported(self):
        form = {"dx": "x", "seed": "a", "n_poly": "b", "fam_count": "0",
                "uf_count": "0"}
        p, errs = _params_from_form(form, {})
        self.assertTrue(any("Domain X" in e for e in errs))
        self.assertTrue(any("Seed" in e for e in errs))
        self.assertTrue(any("Number of fractures" in e for e in errs))
        self.assertNotIn("seed", p)


class DefaultParamsTests(unittest.TestCase):
    def test_shape_of_defaults(self):
        d = default_params()
        self.assertEqual(d["domain"], [6.0, 6.0, 6.0])
        self.assertEqual(d["h"], 0.35)
        self.assertEqual(d["seed"], 42)
        self.assertEqual(d["ncpu"], 4)
        self.assertTrue(d["mesh_dfm"])
        self.assertEqual(d["n_poly"], 24)
        self.assertEqual(d["boundary_faces"], [1, 1, 0, 0, 0, 0])
        self.assertTrue(d["ignore_boundary_faces"])
        self.assertEqual(len(d["families"]), 2)
        self.assertEqual(d["fractures"], [])
        # matches the DEFAULT_FAMILIES used by the driver
        self.assertEqual(d["families"], DEFAULT_FAMILIES)

    def test_copies_are_independent(self):
        d1, d2 = default_params(), default_params()
        d1["families"][0]["constant"] = 99
        self.assertEqual(d2["families"][0]["constant"], 2.0)

    def test_defaults_generate_a_valid_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = write_driver_script(Path(tmp), "reset_case",
                                       default_params()).read_text()
            compile(code, "dfn_driver.py", "exec")
            self.assertIn("nPoly']['value'] = 24", code)


if __name__ == "__main__":
    unittest.main()
