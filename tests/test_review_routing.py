import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import config
from src.trial_map_manager import TrialMapManager

logger.remove()


def _doc(match):
    return {"nct_id": "NCT0", "treatment_list": {"step": [{"match": match}]}}


class TestReviewRouting(unittest.TestCase):
    """
    A trial with no diagnosis criterion is not discarded and is not published
    either. Discarding it is the worst outcome - a trial absent from
    MatchMiner is one no patient can be matched to and no reviewer can see is
    missing - but as it stands it would match every patient in the database,
    so it goes to the review queue instead of the normal output.
    """

    def test_a_trial_with_a_diagnosis_goes_to_the_normal_output(self):
        doc = _doc([{"clinical": {"oncotree_primary_diagnosis": "Neuroblastoma"}}])
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT1"), "cache/ctml")

    def test_a_trial_without_one_goes_to_review(self):
        doc = _doc([{"genomic": {"hugo_symbol": "MYCN", "variant_category": "Mutation"}}])
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT2"),
            config.CTML_REVIEW_PATH)

    def test_a_wildcard_counts_as_a_diagnosis(self):
        # A basket trial is deliberately broad, not undetermined.
        doc = _doc([{"clinical": {"oncotree_primary_diagnosis": "_SOLID_"}}])
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT3"), "cache/ctml")

    def test_an_arm_level_diagnosis_counts(self):
        # The diagnosis need not be at trial level to make the trial usable.
        doc = _doc([{"and": [{"or": [
            {"clinical": {"oncotree_primary_diagnosis": "Ewing Sarcoma"}}]}]}])
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT4"), "cache/ctml")


if __name__ == '__main__':
    unittest.main()
