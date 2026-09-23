"""
The map-time scope filter: which cached trials are oncology trials.

Cases are real trials from the cache, including the four the first
vocabulary skipped wrongly.
"""
import csv
import glob
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.oncology_scope as scope

logger.remove()
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _nct(conditions, title="", official="", keywords=()):
    return {"protocolSection": {
        "conditionsModule": {"conditions": list(conditions), "keywords": list(keywords)},
        "identificationModule": {"briefTitle": title, "officialTitle": official}}}


class TestAssess(unittest.TestCase):

    def assertScope(self, data, expected, trial_id="NCT00000000"):
        in_scope, why = scope.assess(trial_id, data, "nct", overrides={})
        self.assertEqual(in_scope, expected, why)

    def test_non_oncology_is_out(self):
        self.assertScope(_nct(["Generalized Myasthenia Gravis"], "Efgartigimod in children"), False)
        self.assertScope(_nct(["Common Wart", "Plantar Wart"]), False)

    def test_the_first_vocabulary_misses_are_in(self):
        self.assertScope(_nct(["Germinoma"]), True)
        self.assertScope(_nct(["NSCLC"]), True)
        self.assertScope(_nct(["Kaposiform Hemangioendothelioma"]), True)
        self.assertScope(_nct(["Congenital Hyperinsulinism", "Insulinoma"]), True)

    def test_the_official_title_counts(self):
        # NCT05088226: the condition is the procedure; the disease is in the title.
        self.assertScope(_nct(["Peripheral Blood Stem Cell Transplantation"],
                              official="Bu/CY Conditioning for Patients With Acute B Cell "
                                       "Lymphoblast Leukemia"), True)

    def test_abbreviations_are_case_sensitive(self):
        self.assertScope(_nct(["Relapsed ALL"]), True)
        self.assertScope(_nct(["Asthma"], "A study for all children"), False)

    def test_an_oncotree_condition_is_in(self):
        self.assertScope(_nct(["Neuroblastoma"]), True)


class TestOverrides(unittest.TestCase):

    def _file(self, body):
        path = os.path.join(tempfile.mkdtemp(), "overrides.tsv")
        with open(path, "w") as handle:
            handle.write("# comment\ntrial_id\tdecision\treason\n" + body)
        return path

    def test_an_override_wins_in_both_directions(self):
        o = scope.load_overrides(self._file("NCT1\tmap\tsupportive care in oncology\n"
                                            "NCT2\tskip\trollover only\n"))
        self.assertTrue(scope.assess("NCT1", _nct(["Warts"]), "nct", o)[0])
        self.assertFalse(scope.assess("NCT2", _nct(["Neuroblastoma"]), "nct", o)[0])

    def test_a_bad_decision_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            scope.load_overrides(self._file("NCT1\tmaybe\t\n"))

    def test_the_committed_overrides_file_parses(self):
        scope.load_overrides(os.path.join(ROOT, "ref", "scope_overrides.tsv"))


class TestReport(unittest.TestCase):

    def test_one_registry_does_not_erase_the_other(self):
        path = os.path.join(tempfile.mkdtemp(), "out.tsv")
        scope.write_report([("NCT1", "nct", "r")], path, registry="nct")
        scope.write_report([("2023-1", "ctis", "r")], path, registry="ctis")
        scope.write_report([("NCT2", "nct", "r")], path, registry="nct")
        with open(path) as handle:
            ids = [r[0] for r in list(csv.reader(handle, delimiter="\t"))[1:]]
        self.assertEqual(sorted(ids), ["2023-1", "NCT2"])


class TestCuratedTrialsAreInScope(unittest.TestCase):
    """No trial a curator has already mapped may be skipped."""

    def test_every_reviewed_trial_is_in_scope(self):
        for path in glob.glob(os.path.join(ROOT, "ctml", "reviewed", "*.yaml")):
            trial_id = os.path.basename(path)[:-5]
            registry = "nct" if trial_id.startswith("NCT") else "ctis"
            cached = os.path.join(ROOT, "cache", registry, f"{trial_id}.json")
            if not os.path.exists(cached):
                continue
            with open(cached) as handle:
                data = json.load(handle)
            in_scope, why = scope.assess(trial_id, data, registry, overrides={})
            self.assertTrue(in_scope, f"{trial_id}: {why}")


if __name__ == "__main__":
    unittest.main()
