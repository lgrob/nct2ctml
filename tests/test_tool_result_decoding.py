"""
Full run 2026-09-25: 4 of 7,818 tool answers came back as a string (the
model's tool input was not valid JSON), and each lost its trial to an
AttributeError. The real string from NCT06925464 is used below, shortened.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.ai_helper as ai
from utils.llm_platforms import decode_tool_result

logger.remove()

MISSING_BRACE = ('{\n  "cancer_condition": "T-Cell Non-Hodgkin Lymphoma",\n  "oncotree_diagnoses": [\n'
                 '    "Peripheral T-Cell lymphoma, NOS",\n    "Mycosis Fungoides"\n  ]\n')


class TestDecodeToolResult(unittest.TestCase):

    def test_objects_pass_through(self):
        self.assertEqual(decode_tool_result({"a": 1}), {"a": 1})
        self.assertEqual(decode_tool_result([1]), [1])
        self.assertIsNone(decode_tool_result(None))

    def test_a_json_string_is_decoded(self):
        self.assertEqual(decode_tool_result('{"a": [1, 2]}'), {"a": [1, 2]})

    def test_a_missing_closing_brace_is_repaired(self):
        out = decode_tool_result(MISSING_BRACE, "tool_use", "NCT06925464")
        self.assertEqual(out["oncotree_diagnoses"], ["Peripheral T-Cell lymphoma, NOS", "Mycosis Fungoides"])

    def test_no_repair_when_the_answer_was_cut_short(self):
        self.assertIsNone(decode_tool_result(MISSING_BRACE, "max_tokens"))

    def test_brackets_inside_strings_are_not_counted(self):
        self.assertEqual(decode_tool_result('{"a": "x [y {z"', "tool_use"), {"a": "x [y {z"})

    def test_trailing_text_after_a_complete_object_is_ignored(self):
        # NCT07662369: a closed object followed by tool-call markup.
        out = decode_tool_result('{"oncotree_diagnoses": ["Hodgkin Lymphoma"]}\nantml:parameter>\n</invoke>', "tool_use")
        self.assertEqual(out, {"oncotree_diagnoses": ["Hodgkin Lymphoma"]})

    def test_other_damage_is_no_answer(self):
        for bad in ('{"a": 1]', '{"a": ', "not json at all", '{"a": "unterminated'):
            self.assertIsNone(decode_tool_result(bad, "tool_use"), bad)


class TestDiagnosisGuard(unittest.TestCase):

    def test_a_non_object_answer_becomes_no_diagnosis(self):
        for bad in (MISSING_BRACE, None, {}):
            self.assertEqual(ai.keep_candidates(bad, ["Mycosis Fungoides"], "T"), {"oncotree_diagnoses": []})



class TestEmptyDiagnosisRoutesToReview(unittest.TestCase):

    def test_an_empty_diagnosis_list_is_no_diagnosis(self):
        from src.trial_map_manager import TrialMapManager as M
        empty = {"treatment_list": {"step": [{"match": [{"and": [{"clinical": {"oncotree_primary_diagnosis": []}}]}]}]}}
        full = {"treatment_list": {"step": [{"match": [{"or": [{"clinical": {"oncotree_primary_diagnosis": "Hodgkin Lymphoma"}}]}]}]}}
        self.assertFalse(M._has_diagnosis(empty))
        self.assertTrue(M._has_diagnosis(full))



class TestRecordWithoutArmGroups(unittest.TestCase):

    def test_general_fields_map_without_arm_groups(self):
        # NCT06383338 (full run 2026-09-25) has interventions but no armGroups.
        import copy, json
        import src.clinical_trials_gov as ctg
        import src.ctml_schema as cs
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(root, "cache", "nct", "NCT04732065.json")
        if not os.path.exists(path):
            self.skipTest("cached record not present")
        record = json.load(open(path))
        record = copy.deepcopy(record)
        record["protocolSection"]["armsInterventionsModule"].pop("armGroups", None)
        schema = ctg.map_ctml_general_fields(cs.get_ctml_schema(), record)
        self.assertEqual(schema["treatment_list"]["step"][0]["arm"], [])


if __name__ == "__main__":
    unittest.main()
