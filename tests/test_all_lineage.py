"""ALL without a lineage gets T-ALL beside B-ALL (2026-09-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.review_helper as rh

logger.remove()


class TestAllLineage(unittest.TestCase):

    def test_unqualified_all(self):
        self.assertTrue(rh.all_lineage_unspecified([rh.B_ALL], "Patients with acute leukemias (AML, ALL) in CR", ""))

    def test_lineage_wording_blocks_it(self):
        for inc in ("CD19-positive ALL", "Ph+ ALL", "relapsed B-cell ALL", "ALL; blinatumomab arm", "ALL or T-ALL"):
            self.assertFalse(rh.all_lineage_unspecified([rh.B_ALL], inc, ""), inc)
        self.assertFalse(rh.all_lineage_unspecified([rh.B_ALL], "relapsed ALL", "T-ALL"))

    def test_the_word_all_is_not_the_disease(self):
        self.assertFalse(rh.all_lineage_unspecified([rh.B_ALL], "all patients must consent", ""))

    def test_sibling_added_in_or_and_wrapped_alone(self):
        t = {"and": [{"or": [{"clinical": {"oncotree_primary_diagnosis": rh.B_ALL}}]}]}
        self.assertEqual(rh.add_sibling_diagnosis(t, rh.B_ALL, rh.T_ALL), 1)
        self.assertEqual([n["clinical"]["oncotree_primary_diagnosis"] for n in t["and"][0]["or"]], [rh.B_ALL, rh.T_ALL])
        t = {"and": [{"clinical": {"oncotree_primary_diagnosis": rh.B_ALL, "age_numerical": "<22"}}]}
        rh.add_sibling_diagnosis(t, rh.B_ALL, rh.T_ALL)
        alts = t["and"][0]["or"]
        self.assertEqual([(n["clinical"]["oncotree_primary_diagnosis"], n["clinical"]["age_numerical"]) for n in alts],
                         [(rh.B_ALL, "<22"), (rh.T_ALL, "<22")])


if __name__ == "__main__":
    unittest.main()
