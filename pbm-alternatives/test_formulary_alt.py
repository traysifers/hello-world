"""Run with:  python3 -m unittest test_formulary_alt   (from this folder)"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import formulary_alt as fa  # noqa: E402

DATA = fa.load_data()


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fa.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class DataTests(unittest.TestCase):
    def test_every_agent_has_required_fields(self):
        for key, cls in DATA["classes"].items():
            self.assertTrue(cls["agents"], key)
            for a in cls["agents"]:
                for field in ("generic", "brands", "device", "frequency"):
                    self.assertIn(field, a, "%s/%s" % (key, a.get("generic")))
                for tier in (a.get("strengths") or {}).values():
                    self.assertIn(tier, cls["tiers"], "%s/%s tier %s" % (key, a["generic"], tier))

    def test_related_classes_exist(self):
        for key, cls in DATA["classes"].items():
            for r in cls.get("related", []):
                self.assertIn(r, DATA["classes"], "%s -> %s" % (key, r))


class MatchTests(unittest.TestCase):
    def test_brand_with_strength_gets_tier(self):
        code, out, _ = run("Advair Diskus 250/50")
        self.assertEqual(code, 0)
        self.assertIn("medium-dose ICS tier", out)
        self.assertIn("Symbicort, Breyna) 160/4.5 mcg", out)
        self.assertNotIn("- Fluticasone propionate/salmeterol DPI (Advair Diskus", out)  # denied drug excluded

    def test_pasted_message_with_hyphenated_strength(self):
        code, out, _ = run("Rx change request: Dulera 100-5 mcg is non-formulary, please consider alternative")
        self.assertEqual(code, 0)
        self.assertIn("Dulera 100/5 mcg", out)
        self.assertIn("medium-dose ICS tier", out)

    def test_more_specific_brand_wins(self):
        code, out, _ = run("Advair HFA 115/21")
        self.assertEqual(code, 0, out)
        self.assertIn("Denied: Advair HFA 115/21 mcg", out)

    def test_bare_generic_is_ambiguous(self):
        code, _, err = run("fluticasone")
        self.assertEqual(code, 2)
        self.assertIn("--class incs", err)
        self.assertIn("--class ics-laba", err)

    def test_class_flag_narrows_ambiguity(self):
        code, _, err = run("fluticasone", "--class", "incs")
        self.assertEqual(code, 2)                      # still two nasal fluticasones
        self.assertNotIn("--class ics", err.replace("--class incs", ""))
        code, out, _ = run("fluticasone furoate", "--class", "incs")
        self.assertEqual(code, 0, out)
        self.assertIn("Denied: fluticasone furoate nasal", out)

    def test_typo_fuzzy_match(self):
        code, out, _ = run("symbicrot 160/4.5")
        self.assertEqual(code, 0)
        self.assertIn("Symbicort 160/4.5", out)

    def test_exact_match_beats_fuzzy_neighbor(self):
        code, out, _ = run("omeprazole 20 mg")
        self.assertEqual(code, 0, out)
        self.assertIn("Denied: omeprazole 20 mg", out)

    def test_unknown_drug(self):
        code, _, err = run("metformin 500 mg")
        self.assertEqual(code, 2)
        self.assertIn("No drug", err)

    def test_topical_steroid_potency_class(self):
        code, out, _ = run("clobetasol 0.05% cream")
        self.assertEqual(code, 0)
        self.assertIn("potency class 1", out)
        self.assertIn("Halobetasol", out)
        self.assertNotIn("Desonide", out)  # class 6 is too far from class 1

    def test_oral_steroid_mg_equivalence(self):
        code, out, _ = run("Orapred ODT 15 mg")
        self.assertEqual(code, 0)
        self.assertIn("12 mg ~ prednisolone 15 mg", out)      # methylprednisolone
        self.assertIn("2.25 mg ~ prednisolone 15 mg", out)    # dexamethasone

    def test_epipen_jr_weight_tier(self):
        code, out, _ = run("EpiPen Jr 2-pak")
        self.assertEqual(code, 0)
        self.assertIn("0.15 mg dose (15 to <30 kg)", out)
        self.assertIn("neffy) 1 mg", out)
        self.assertNotIn("0.3 mg -", out)

    def test_multi_class_drug_gets_sections(self):
        code, out, _ = run("Dupixent 300 mg")
        self.assertEqual(code, 0)
        self.assertGreaterEqual(out.count("If prescribed for"), 2)
        self.assertIn("specialty agents", out)

    def test_single_agent_class_has_related_hint(self):
        code, out, _ = run("Atrovent nasal 0.03%")
        self.assertEqual(code, 0)
        self.assertIn("No same-class alternative", out)
        self.assertIn("Related classes", out)

    def test_patient_name_in_opener(self):
        _, out, _ = run("Flonase", "--patient", "J. Doe")
        self.assertTrue(out.startswith("Pharmacy sent an Rx-change request for Flonase (J. Doe);"))

    def test_json_output(self):
        code, out, _ = run("Breo 100/25", "--json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["sections"][0]["tier"], "medium")


class MemoryTests(unittest.TestCase):
    def test_record_then_annotate(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = os.path.join(tmp, "mem.json")
            code, out, _ = run("--record", "covered", "--pbm", "Caremark", "Wixela 250/50", "--memory", mem)
            self.assertEqual(code, 0, out)
            code, out, err = run("Advair HFA 115/21", "--pbm", "Caremark", "--memory", mem)
            self.assertEqual(code, 0)
            self.assertIn("[covered on Caremark", out)
            self.assertIn("denied on Caremark", err)   # the denial itself was auto-recorded
            code, out, _ = run("--history", "--memory", mem)
            self.assertIn("covered", out)
            self.assertIn("denied", out)
            code, out, _ = run("Advair HFA 115/21", "--pbm", "Caremark", "--memory", mem, "--no-record")
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
