"""
The deterministic diagnosis path gives the committed baseline on frozen
records (bench/conditions_baseline.py). A change here changes what reaches
the model as its diagnosis floor: if it is intended, run
`python -m bench.conditions_baseline --update` and commit the new baseline.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

from bench import conditions_baseline as cb

logger.remove()


class TestConditionsBaseline(unittest.TestCase):
    def test_diagnoses_and_means_match_the_baseline(self):
        with open(cb.BASELINE) as handle:
            baseline = json.load(handle)
        found = cb.differences(cb.compute(), baseline)
        self.assertEqual(found, [], "\n" + "\n".join(found) + "\n" + __doc__)

    def test_every_curated_nct_trial_has_a_fixture(self):
        with open(cb.BASELINE) as handle:
            trials = json.load(handle)["trials"]
        missing = [t for t in trials if not os.path.exists(os.path.join(cb.FIXTURES, f"{t}.json"))]
        self.assertEqual(missing, [])

    def test_differences_names_the_trial_and_the_diagnosis(self):
        before = {"trials": {"NCT1": ["A", "B"]}, "means": {"dx_r": 1.0}}
        after = {"trials": {"NCT1": ["A", "C"]}, "means": {"dx_r": 0.5}}
        self.assertEqual(
            cb.differences(after, before), ["NCT1: +['C'] -['B']", "mean dx_r: 1.0 -> 0.5"]
        )


if __name__ == "__main__":
    unittest.main()
