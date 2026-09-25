"""
Roadmap 1.8: diagnosis answers are checked in code against the candidate
list their call offered, and a trial with an off-list Oncotree answer goes
to review. Also pins that bulk `map --all` routes NCT trials to review, which
it did not until 2026-09-24.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import utils.ai_helper as ai
from src.trial_map_manager import TrialMapManager

logger.remove()


class TestKeepCandidates(unittest.TestCase):

    def setUp(self):
        ai.reset_enum_cap_events()
        ai.OFF_LIST_BY_TRIAL.clear()

    def test_on_list_answers_are_kept(self):
        r = ai.keep_candidates({"oncotree_diagnoses": ["Neuroblastoma"]}, {"Neuroblastoma", "Ganglioneuroma"}, "T")
        self.assertEqual(r["oncotree_diagnoses"], ["Neuroblastoma"])
        self.assertEqual(ai.OFF_LIST_BY_TRIAL, {})

    def test_case_only_difference_is_recased_to_the_candidate(self):
        r = ai.keep_candidates({"oncotree_diagnoses": ["neuroblastoma"]}, {"Neuroblastoma"}, "T")
        self.assertEqual(r["oncotree_diagnoses"], ["Neuroblastoma"])
        self.assertEqual(ai.OFF_LIST_EVENTS["recased"], 1)

    def test_a_string_that_is_not_an_oncotree_name_is_dropped(self):
        # "Lymphoma" on NCT02332668, once per saved Haiku replicate.
        r = ai.keep_candidates({"oncotree_diagnoses": ["Lymphoma", "Melanoma"]}, {"Melanoma"}, "NCT02332668")
        self.assertEqual(r["oncotree_diagnoses"], ["Melanoma"])
        self.assertEqual(ai.OFF_LIST_EVENTS["dropped"], 1)
        self.assertEqual(ai.OFF_LIST_BY_TRIAL, {})

    def test_a_valid_off_list_name_is_kept_and_recorded_for_review(self):
        # "Neuroblastoma" on NCT03838042: named in the text and in the key, but
        # stage 1 had not offered Peripheral Nervous System.
        r = ai.keep_candidates({"oncotree_diagnoses": ["Neuroblastoma", "Medulloblastoma"]},
                               {"Medulloblastoma"}, "NCT03838042")
        self.assertEqual(r["oncotree_diagnoses"], ["Neuroblastoma", "Medulloblastoma"])
        self.assertEqual(ai.OFF_LIST_BY_TRIAL, {"NCT03838042": {"Neuroblastoma"}})

    def test_level_1_answers_off_the_list_are_dropped_even_if_valid(self):
        # The caller uses a level-1 answer as a branch key.
        r = ai.keep_candidates({"oncotree_diagnoses": [{"cancer_condition": "x", "oncotree_value": "Neuroblastoma"},
                                                       {"cancer_condition": "y", "oncotree_value": "Other"}]},
                               {"CNS/Brain"}, "T", extra=("", "Other"), keep_valid=False)
        self.assertEqual([i["oncotree_value"] for i in r["oncotree_diagnoses"]], ["Other"])
        self.assertEqual(ai.OFF_LIST_BY_TRIAL, {})

    def test_malformed_results_become_no_diagnosis(self):
        # Changed 2026-09-25: passing malformed results through lost 4 trials
        # of the full run to exceptions in the callers.
        for bad in ({}, None, "text", {"oncotree_diagnoses": "x"}):
            self.assertEqual(ai.keep_candidates(bad, {"A"}, "T")["oncotree_diagnoses"], [], bad)


class TestOffListRouting(unittest.TestCase):

    def test_recorded_terms_are_written_and_route_to_review(self):
        ai.OFF_LIST_BY_TRIAL.clear()
        ai.OFF_LIST_BY_TRIAL["NCT3"] = {"Neuroblastoma"}
        doc = {"treatment_list": {"step": [{"match": [{"clinical": {"oncotree_primary_diagnosis": "Medulloblastoma"}}]}]}}
        TrialMapManager._record_off_list(doc, "NCT3")
        self.assertEqual(doc["diagnosis_off_list"], "Neuroblastoma")
        self.assertNotIn("NCT3", ai.OFF_LIST_BY_TRIAL)
        with mock.patch.object(config, "CTML_REVIEW_PATH", tempfile.mkdtemp()):
            self.assertEqual(TrialMapManager._destination_for(doc, "cache/ctml", "NCT3"), config.CTML_REVIEW_PATH)


class TestBulkMappingRoutes(unittest.TestCase):

    def test_map_all_trials_sends_a_trial_without_diagnosis_to_review(self):
        src, out, review = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        json.dump({"protocolSection": {}}, open(os.path.join(src, "NCT9.json"), "w"))
        mgr = TrialMapManager.__new__(TrialMapManager)
        status = {"NCT9": {"entry_last_updated_date": "2999-01-01", "status": "open"}}
        with mock.patch.object(TrialMapManager, "load_trial_status_dict", return_value=status), \
             mock.patch.object(TrialMapManager, "load_local_trial_dict", return_value={}), \
             mock.patch.object(TrialMapManager, "get_gene_synonym_mapping", return_value={}), \
             mock.patch.object(TrialMapManager, "_add_local_trial_info", return_value=None), \
             mock.patch.object(config, "SKIP_OUT_OF_SCOPE_AT_MAP", False), \
             mock.patch.object(config, "CTML_REVIEW_PATH", review), \
             mock.patch("src.clinical_trials_gov.map_nct_to_ctml",
                        return_value={"nct_id": "NCT9", "treatment_list": {"step": [{"match": []}]}}):
            mgr.map_all_trials(src, out)
        self.assertEqual(os.listdir(out), [])
        self.assertEqual(os.listdir(review), ["NCT9.yaml"])


if __name__ == "__main__":
    unittest.main()
