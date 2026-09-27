"""The ClinicalTrials.gov split finds the Exclusion Criteria heading, not the phrase (2026-09-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import src.clinical_trials_gov as ctg

logger.remove()


class TestExclusionHeading(unittest.TestCase):

    def test_preamble_phrases_are_skipped(self):
        for pre in ("All participants must meet the following inclusion and exclusion criteria.",
                    "*When alectinib-specific inclusion/exclusion criteria overlap, use these.",
                    "provided all inclusion and exclusion criteria are met.",
                    "Patients will be ineligible if they meet any of the exclusion criteria below"):
            text = f"{pre} Diagnosis of neuroblastoma. Exclusion Criteria: * Pregnancy"
            i = ctg.exclusion_heading(text)
            self.assertEqual(text[i:i + 20], "Exclusion Criteria: ", pre)

    def test_a_plain_heading_is_found(self):
        text = "Inclusion Criteria: * Age 1-21 EXCLUSION CRITERIA: * Pregnancy"
        self.assertEqual(ctg.exclusion_heading(text), text.index("EXCLUSION"))

    def test_no_heading(self):
        self.assertIsNone(ctg.exclusion_heading("Inclusion Criteria: * Age 1-21 * no prior therapy"))


if __name__ == "__main__":
    unittest.main()
