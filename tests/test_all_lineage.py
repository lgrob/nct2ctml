"""ALL without a lineage gets T-ALL beside B-ALL (2026-09-27)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import src.text_rules as text_rules

logger.remove()


class TestAllLineage(unittest.TestCase):
    def test_unqualified_all(self):
        self.assertTrue(
            text_rules.all_lineage_unspecified(
                [text_rules.B_ALL], "Patients with acute leukemias (AML, ALL) in CR", ""
            )
        )

    def test_lineage_wording_blocks_it(self):
        for inc in (
            "CD19-positive ALL",
            "Ph+ ALL",
            "relapsed B-cell ALL",
            "ALL; blinatumomab arm",
            "ALL or T-ALL",
        ):
            self.assertFalse(text_rules.all_lineage_unspecified([text_rules.B_ALL], inc, ""), inc)
        self.assertFalse(
            text_rules.all_lineage_unspecified([text_rules.B_ALL], "relapsed ALL", "T-ALL")
        )

    def test_the_word_all_is_not_the_disease(self):
        self.assertFalse(
            text_rules.all_lineage_unspecified([text_rules.B_ALL], "all patients must consent", "")
        )

    def test_sibling_added_in_or_and_wrapped_alone(self):
        t = {"and": [{"or": [{"clinical": {"oncotree_primary_diagnosis": text_rules.B_ALL}}]}]}
        self.assertEqual(text_rules.add_sibling_diagnosis(t, text_rules.B_ALL, text_rules.T_ALL), 1)
        self.assertEqual(
            [n["clinical"]["oncotree_primary_diagnosis"] for n in t["and"][0]["or"]],
            [text_rules.B_ALL, text_rules.T_ALL],
        )
        t = {
            "and": [
                {
                    "clinical": {
                        "oncotree_primary_diagnosis": text_rules.B_ALL,
                        "age_numerical": "<22",
                    }
                }
            ]
        }
        text_rules.add_sibling_diagnosis(t, text_rules.B_ALL, text_rules.T_ALL)
        alts = t["and"][0]["or"]
        self.assertEqual(
            [
                (n["clinical"]["oncotree_primary_diagnosis"], n["clinical"]["age_numerical"])
                for n in alts
            ],
            [(text_rules.B_ALL, "<22"), (text_rules.T_ALL, "<22")],
        )


if __name__ == "__main__":
    unittest.main()
