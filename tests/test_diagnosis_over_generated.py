import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import utils.llm.schema as ls
import utils.oncotree as onct
from src.trial_map_manager import TrialMapManager

logger.remove()


def _answer(values, allowed, trial_id="NCT0", **kw):
    ls.OVER_GENERATION_BY_TRIAL.pop(trial_id, None)
    ls.keep_candidates({"oncotree_diagnoses": list(values)}, list(allowed), trial_id, **kw)
    return ls.OVER_GENERATION_BY_TRIAL.get(trial_id)


class TestCandidateListBackIsANonAnswer(unittest.TestCase):
    """
    NCT04732065 and NCT06528691 each came back with 126 diagnoses from both
    models on the 2026-09-30 Ollama benchmark, against 4 and 1 curated. 126 is
    not a judgement: it is the size of the stage-2 candidate list a level-1
    answer of CNS/Brain offers, the whole Oncotree subtree with the root
    itself left out. keep_candidates checks membership, so every one of those
    answers passed; nothing looked at how many there were.
    """

    def test_the_cns_brain_branch_is_still_126_terms(self):
        # The number in the benchmark report, and the reason it was identical
        # for two different models. A reference update may move it; the rule
        # does not depend on the value, this test only pins the diagnosis.
        _, l1_to_all = onct.get_all_oncotree_data()
        self.assertEqual(len(l1_to_all["CNS/Brain"]), 126)
        self.assertNotIn("CNS/Brain", l1_to_all["CNS/Brain"])

    def test_a_whole_branch_answer_is_recorded(self):
        branch = [f"Dx{i}" for i in range(126)]
        self.assertEqual(_answer(branch, branch), "126 of 126 candidates")

    def test_a_curated_sized_answer_is_not(self):
        # The widest curated key takes 5 of 23 (2023-505575-69-01, 0.217).
        branch = [f"Dx{i}" for i in range(23)]
        self.assertIsNone(_answer(branch[:5], branch))

    def test_the_threshold_is_the_configured_share(self):
        branch = [f"Dx{i}" for i in range(100)]
        share = config.DIAGNOSIS_OVER_GENERATION_SHARE
        self.assertIsNotNone(_answer(branch[: int(share * 100)], branch))
        self.assertIsNone(_answer(branch[: int(share * 100) - 1], branch))

    def test_a_short_branch_is_left_alone(self):
        # Peritoneum offers 2 terms and Prostate 5: one right answer is
        # already half the list, so the floor keeps the rule off them.
        for n in (2, 5, config.DIAGNOSIS_OVER_GENERATION_MIN_LIST - 1):
            branch = [f"Dx{i}" for i in range(n)]
            self.assertIsNone(_answer(branch, branch), f"fired on a {n}-term branch")

    def test_the_level_1_extras_are_not_counted_as_candidates(self):
        # The level-1 schema also permits "" and "Other"; they are not
        # candidates and must not pad the denominator.
        branch = [f"Dx{i}" for i in range(20)]
        got = _answer(branch[:8] + ["Other"], branch, extra=("", "Other"), keep_valid=False)
        self.assertEqual(got, "8 of 20 candidates")

    def test_the_worst_call_of_a_trial_is_the_one_kept(self):
        small = [f"Dx{i}" for i in range(20)]
        big = [f"Ex{i}" for i in range(100)]
        ls.OVER_GENERATION_BY_TRIAL.pop("NCT_WORST", None)
        ls.keep_candidates({"oncotree_diagnoses": small[:9]}, small, "NCT_WORST")
        ls.keep_candidates({"oncotree_diagnoses": big}, big, "NCT_WORST")
        ls.keep_candidates({"oncotree_diagnoses": small[:9]}, small, "NCT_WORST")
        self.assertEqual(ls.OVER_GENERATION_BY_TRIAL["NCT_WORST"], "100 of 100 candidates")


class TestOverGeneratedRouting(unittest.TestCase):
    def test_the_record_reaches_the_ctml_and_routes_to_review(self):
        ls.OVER_GENERATION_BY_TRIAL["NCT_OG"] = "126 of 126 candidates"
        doc = {
            "nct_id": "NCT_OG",
            "treatment_list": {
                "step": [
                    {"match": [{"clinical": {"oncotree_primary_diagnosis": "Diffuse Glioma"}}]}
                ]
            },
        }
        TrialMapManager._record_over_generated_diagnoses(doc, "NCT_OG")
        self.assertEqual(doc["diagnosis_over_generated"], "126 of 126 candidates")
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT_OG"),
            config.CTML_REVIEW_PATH,
        )

    def test_a_trial_without_the_record_is_published(self):
        doc = {
            "nct_id": "NCT_OK",
            "treatment_list": {
                "step": [
                    {"match": [{"clinical": {"oncotree_primary_diagnosis": "Diffuse Glioma"}}]}
                ]
            },
        }
        TrialMapManager._record_over_generated_diagnoses(doc, "NCT_OK")
        self.assertNotIn("diagnosis_over_generated", doc)
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT_OK"), "cache/ctml"
        )


if __name__ == "__main__":
    unittest.main()
