import json
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import src.clinical_trials_gov as ctg
import src.match_criteria_mapper as mcm


def _trial(minimum=None, maximum=None):
    eligibility = {}
    if minimum is not None:
        eligibility["minimumAge"] = minimum
    if maximum is not None:
        eligibility["maximumAge"] = maximum
    return {"protocolSection": {"identificationModule": {"nctId": "NCT00000000"},
                                "eligibilityModule": eligibility}}


class TestAgeBounds(unittest.TestCase):
    """
    maximumAge used to be discarded, so every trial was open-ended at the top.
    613 of the 924 cached trials state one and 56 cap below 18, which in a
    paediatric service is the difference between a neonatal study matching
    neonates and it matching every child in the database.
    """

    def test_both_bounds_are_emitted(self):
        self.assertEqual(ctg.map_age_numerical(_trial("1 Year", "14 Years")),
                         [">=1", "<=15"])

    def test_either_bound_alone(self):
        self.assertEqual(ctg.map_age_numerical(_trial("18 Years", None)), [">=18"])
        self.assertEqual(ctg.map_age_numerical(_trial(None, "17 Years")), ["<=18"])
        self.assertEqual(ctg.map_age_numerical(_trial(None, None)), [])

    def test_the_maximum_is_in_completed_units(self):
        """
        maximumAge "17 Years" describes a participant who is 17 until the day
        they turn 18, so the eligible set is age < 18. MatchMiner compares
        against a birth date, where "<=17" admits only up to 17.0 and drops
        every eligible 17-to-18-year-old - the AYA group.

        The registry's own trials settle the reading: NCT02443831 pairs
        maximumAge "24 Years" with "24 years or younger"; NCT03643276 pairs
        "17 Years" with "age < 18 years (up to 17 years and 365 days)".
        """
        self.assertEqual(ctg.map_age_numerical(_trial(None, "24 Years")), ["<=25"])
        self.assertEqual(ctg.map_age_numerical(_trial(None, "21 Years")), ["<=22"])

    def test_the_minimum_is_exact(self):
        """A lower bound admits a patient the day they reach it; no offset."""
        self.assertEqual(ctg.map_age_numerical(_trial("1 Year", None)), [">=1"])
        self.assertEqual(ctg.map_age_numerical(_trial("6 Months", None)), [">=0.5"])

    def test_sub_year_units_on_both_ends(self):
        """
        A neonatal study. MatchMiner reads the fraction as a fraction of a
        year and rounds it to whole months, which is the same reading this
        conversion intends - so the one-unit offset on a day-scale maximum
        disappears below its granularity, as it should.
        """
        self.assertEqual(ctg.map_age_numerical(_trial("18 Days", "70 Days")),
                         [">=0.05", "<=0.19"])
        self.assertEqual(ctg.map_age_numerical(_trial("6 Months", "18 Months")),
                         [">=0.5", "<=1.58"])

    def test_unparseable_bounds_are_dropped_not_fatal(self):
        self.assertEqual(ctg.map_age_numerical(_trial("N/A", "14 Years")), ["<=15"])
        self.assertEqual(ctg.map_age_numerical(_trial("1 Year", "14 Fortnights")),
                         [">=1"])


class TestAgeBoundsReachCTML(unittest.TestCase):
    """
    Two age_numerical values cannot share one clinical dict, so the second
    becomes a sibling node. MatchMiner intersects sibling nodes, which is how
    a range is expressed; merging them into one node would not work, because
    its engine flattens a node's query parts into a single dict keyed by field
    and the second bound would overwrite the first.
    """

    @staticmethod
    def _ages(node, out=None):
        out = [] if out is None else out
        if isinstance(node, dict):
            if "age_numerical" in node:
                out.append(node["age_numerical"])
            for v in node.values():
                TestAgeBoundsReachCTML._ages(v, out)
        elif isinstance(node, list):
            for v in node:
                TestAgeBoundsReachCTML._ages(v, out)
        return out

    def test_both_bounds_survive_with_several_diagnoses(self):
        out = mcm.convert_to_ctml_clinical_schema(
            {"oncotree_primary_diagnosis": ["Neuroblastoma", "Ewing Sarcoma"],
             "age_numerical": [">=1", "<=14"]})
        self.assertEqual(sorted(self._ages(out)), ["<=14", ">=1"])

    def test_both_bounds_survive_with_one_diagnosis(self):
        out = mcm.convert_to_ctml_clinical_schema(
            {"oncotree_primary_diagnosis": ["Neuroblastoma"],
             "age_numerical": [">=1", "<=14"]})
        self.assertEqual(sorted(self._ages(out)), ["<=14", ">=1"])

    def test_both_bounds_survive_with_no_diagnosis(self):
        out = mcm.convert_to_ctml_clinical_schema({"age_numerical": [">=1", "<=14"]})
        self.assertEqual(sorted(self._ages(out)), ["<=14", ">=1"])

    def test_a_single_bound_keeps_the_old_flat_shape(self):
        out = mcm.convert_to_ctml_clinical_schema(
            {"oncotree_primary_diagnosis": ["Neuroblastoma"], "age_numerical": [">=1"]})
        self.assertEqual(out, {"clinical": {"age_numerical": ">=1",
                                            "oncotree_primary_diagnosis": "Neuroblastoma"}})

    def test_no_bound_at_all_is_unchanged(self):
        out = mcm.convert_to_ctml_clinical_schema(
            {"oncotree_primary_diagnosis": ["Neuroblastoma"]})
        self.assertEqual(out, {"clinical": {"oncotree_primary_diagnosis": "Neuroblastoma"}})

    def test_the_real_neonatal_trial(self):
        """NCT06776952 enrols 18 to 70 days. Without the upper bound it
        matched every child in the database."""
        path = os.path.join(os.path.dirname(__file__), "..", "cache", "nct",
                            "NCT06776952.json")
        if not os.path.exists(path):
            self.skipTest("cached record not present")
        bounds = ctg.map_age_numerical(json.load(open(path)))
        self.assertEqual(bounds, [">=0.05", "<=0.19"])


if __name__ == '__main__':
    unittest.main()
