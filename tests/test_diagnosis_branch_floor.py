import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import src.clinical_trials_gov as ctg

logger.remove()


class TestBranchFloor(unittest.TestCase):
    """
    Diagnosis mapping picks Oncotree level_1 nodes, then picks children within
    them. A wrong level_1 does not merely bias the second stage - it removes
    the correct answer from the list the model is shown. Neuroblastoma is the
    case that exposed it: Oncotree files it under Peripheral Nervous System,
    while its usual primary site puts "Adrenal Gland" first in any clinician's
    mind, and Adrenal Gland has three children, none of them neuroblastoma.
    """

    def _run(self, seed_terms):
        """Map with stage 1 answering 'Adrenal Gland'; return the stage-2 list."""
        offered = []

        def fake_ai(nct_id, trial_info, oncotree_values):
            offered.append(set(oncotree_values))
            if len(offered) == 1:                      # stage 1: the wrong branch
                return {"oncotree_diagnoses": ["Adrenal Gland"]}
            return {"oncotree_diagnoses": sorted(                # stage 2: honest
                {"Neuroblastoma"} & oncotree_values)}

        with patch.object(ctg.ai, "get_oncotree_diagnoses_from_trial_info",
                          side_effect=fake_ai):
            result = ctg.map_eligibility_criteria_to_oncotree_term(
                "NCT01704716", "high risk neuroblastoma", seed_terms)
        return offered, result

    def test_without_a_seed_the_answer_is_unreachable(self):
        offered, result = self._run(seed_terms=())
        self.assertNotIn("Neuroblastoma", offered[1],
                         "Adrenal Gland's subtree should not contain neuroblastoma")
        self.assertEqual(result, [])

    def test_a_seeded_term_forces_its_own_branch_in(self):
        offered, result = self._run(seed_terms=["Neuroblastoma"])
        self.assertIn("Neuroblastoma", offered[1])
        self.assertIn("Ganglioneuroblastoma", offered[1],
                      "the whole branch is added, not just the seeded term, so "
                      "siblings the trial did not name outright stay reachable")
        self.assertEqual(result, ["Neuroblastoma"])

    def test_the_wrongly_chosen_branch_is_still_offered(self):
        # The floor adds; it never removes. A seed must not narrow the search.
        offered, _ = self._run(seed_terms=["Neuroblastoma"])
        self.assertIn("Pheochromocytoma", offered[1])

    def test_seed_works_when_stage_one_returns_nothing(self):
        offered = []

        def fake_ai(nct_id, trial_info, oncotree_values):
            offered.append(set(oncotree_values))
            if len(offered) == 1:
                return {"oncotree_diagnoses": []}
            return {"oncotree_diagnoses": ["Neuroblastoma"]}

        with patch.object(ctg.ai, "get_oncotree_diagnoses_from_trial_info",
                          side_effect=fake_ai):
            result = ctg.map_eligibility_criteria_to_oncotree_term(
                "NCT01704716", "text", ["Neuroblastoma"])
        self.assertEqual(result, ["Neuroblastoma"])


if __name__ == '__main__':
    unittest.main()
