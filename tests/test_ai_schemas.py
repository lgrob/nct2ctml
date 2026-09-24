import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import utils.ai_helper as ai

logger.remove()


class TestEveryPromptIsStructured(unittest.TestCase):
    """
    Without `format`, Ollama may answer with prose or malformed JSON, and
    parse_response logs a JSONDecodeError and returns an empty dict - so the
    answer is discarded as though the model found nothing. That is invisible
    in the benchmark report, which only shows what survived.
    """

    def test_all_builders_return_a_schema_and_a_prompt(self):
        builders = [
            ai.get_ai_prompt_level1_for_original_conditions(["Neuroblastoma"], ["Adrenal Gland"]),
            ai.get_ai_prompt_oncotree_diagnoses_from_trial_info("t", ["Neuroblastoma"]),
            ai.get_ai_prompt_child_values("neuroblastoma", ["Neuroblastoma"]),
            ai.get_her2_er_pr_status_prompt("c", []),
            ai.get_pdl1_status_prompt("c", []),
            ai.get_mmr_status_prompt("c", []),
            ai.get_disease_status_prompt("c", []),
            ai.get_age_bounds_prompt("c"),
            ai.get_inclusion_genomic_criteria_prompt(["MYCN"], "c"),
            ai.get_exclusion_genomic_criteria_prompt(["MYCN"], "c"),
        ]
        for schema, prompt in builders:
            self.assertIsInstance(schema, dict)
            self.assertIn("type", schema)
            self.assertIsInstance(prompt, str)

    def test_the_schema_reaches_the_request_body(self):
        # Where the schema goes depends on the platform: Ollama's `format`,
        # the Anthropic forced tool's input. Either way it must be sent.
        body = ai._llm_platform.get_request_body("p", ai.PDL1_SCHEMA)
        sent = body.get("format") or body["tools"][0]["input_schema"]["properties"]["result"]
        self.assertEqual(sent, ai.PDL1_SCHEMA)

    def test_the_ollama_platform_sends_it_as_format(self):
        from utils.llm_platforms import OllamaPlatform
        body = OllamaPlatform("llama3.3:70b", "http://127.0.0.1").get_request_body("p", ai.PDL1_SCHEMA)
        self.assertEqual(body.get("format"), ai.PDL1_SCHEMA)


class TestCandidateListsBecomeEnums(unittest.TestCase):
    """
    The diagnosis prompts already say "choose only from the provided
    OncotreeValues". An enum makes that structural rather than advisory:
    "Lymphoma" becomes impossible to emit, not merely wrong.
    """

    def test_allowed_values_become_an_enum(self):
        schema = ai.oncotree_diagnoses_schema(["Neuroblastoma", "Ganglioneuroblastoma"])
        items = schema["properties"]["oncotree_diagnoses"]["items"]
        self.assertEqual(items["enum"], ["Ganglioneuroblastoma", "Neuroblastoma"])

    def test_an_off_list_answer_has_no_representation(self):
        schema = ai.oncotree_diagnoses_schema(["Neuroblastoma"])
        self.assertNotIn(
            "Lymphoma", schema["properties"]["oncotree_diagnoses"]["items"]["enum"])

    def test_level1_keeps_its_escape_hatches(self):
        # clinical_trials_gov skips "" and "other"; a constrained model that
        # cannot say either is forced to pick a branch it does not believe in.
        schema = ai.level1_diagnoses_schema(["Adrenal Gland"])
        values = (schema["properties"]["oncotree_diagnoses"]["items"]
                        ["properties"]["oncotree_value"]["enum"])
        self.assertIn("", values)
        self.assertIn("Other", values)

    def test_a_very_large_candidate_list_drops_the_enum(self):
        # Ollama compiles `format` into a grammar; hundreds of alternatives are
        # slow to build. The shape is still enforced, only the values are not.
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Ollama"):
            schema = ai.oncotree_diagnoses_schema([f"Term {i}" for i in range(500)])
        items = schema["properties"]["oncotree_diagnoses"]["items"]
        self.assertNotIn("enum", items)
        self.assertEqual(items["type"], "string")

    def test_an_empty_candidate_list_is_not_an_empty_enum(self):
        # An empty enum would make every answer invalid.
        items = ai.oncotree_diagnoses_schema([])["properties"]["oncotree_diagnoses"]["items"]
        self.assertNotIn("enum", items)


def _items(schema):
    return schema["properties"]["oncotree_diagnoses"]["items"]


class TestEnumCap(unittest.TestCase):
    """
    Dropping the enum re-opens off-list answers, so it must never be silent,
    and the cap depends on whether the backend compiles a grammar at all.
    """

    def setUp(self):
        ai.reset_enum_cap_events()
        self.logs = []
        self.sink = logger.add(lambda m: self.logs.append(m.record), level="INFO")

    def tearDown(self):
        logger.remove(self.sink)
        ai.reset_enum_cap_events()

    def _terms(self, n):
        return [f"Term {i}" for i in range(n)]

    def _levels(self, level):
        return [r["message"] for r in self.logs if r["level"].name == level]

    def test_over_the_cap_warns_with_trial_and_size_and_counts(self):
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Ollama"):
            items = _items(ai.oncotree_diagnoses_schema(self._terms(438), "NCT02508038"))
        self.assertNotIn("enum", items)
        warnings = self._levels("WARNING")
        self.assertEqual(len(warnings), 1)
        self.assertIn("NCT02508038", warnings[0])
        self.assertIn("438", warnings[0])
        self.assertEqual(ai.ENUM_CAP_EVENTS["dropped"], 1)
        self.assertEqual(ai.ENUM_CAP_EVENTS["largest"], 438)
        self.assertIn("1 dropped", ai.enum_cap_summary())

    def test_the_cap_itself_still_gets_an_enum(self):
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Ollama"):
            items = _items(ai.oncotree_diagnoses_schema(self._terms(400)))
        self.assertEqual(len(items["enum"]), 400)
        self.assertEqual(self._levels("WARNING"), [])

    def test_near_the_cap_is_info_not_warning(self):
        # 370 is the largest list the Haiku benchmark replay sent (NCT02813135).
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Ollama"):
            items = _items(ai.oncotree_diagnoses_schema(self._terms(370), "NCT02813135"))
        self.assertEqual(len(items["enum"]), 370)
        self.assertEqual(self._levels("WARNING"), [])
        self.assertTrue(any("NCT02813135" in m and "370" in m for m in self._levels("INFO")))
        self.assertEqual(ai.ENUM_CAP_EVENTS["near_cap"], 1)

    def test_a_small_list_logs_nothing(self):
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Ollama"):
            ai.oncotree_diagnoses_schema(self._terms(226))
        self.assertEqual(self.logs, [])
        self.assertEqual(ai.ENUM_CAP_EVENTS["enum"], 1)

    def test_anthropic_keeps_the_enum_for_the_whole_oncotree(self):
        # The forced tool call is not strict, so no grammar is compiled; 847 is
        # every Oncotree descendant, the largest list the diagnosis path builds.
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Anthropic"):
            items = _items(ai.oncotree_diagnoses_schema(self._terms(847), "t"))
        self.assertEqual(len(items["enum"]), 847)
        self.assertEqual(self._levels("WARNING"), [])
        self.assertEqual(ai.ENUM_CAP_EVENTS["dropped"], 0)

    def test_the_caps_are_pinned_per_backend(self):
        caps = ai.config.SCHEMA_ENUM_MAX_VALUES
        for platform in ("ollama", "local_ai", "vllm", "sglang"):
            self.assertEqual(caps[platform], 400)
        self.assertIsNone(caps["anthropic"])

    def test_an_unlisted_platform_falls_back_to_400(self):
        with mock.patch.object(ai.config, "LLM_PLATFORM", "SomethingNew"):
            self.assertEqual(ai.max_enum_values(), 400)

    def test_every_diagnosis_builder_names_the_trial(self):
        big = self._terms(401)
        with mock.patch.object(ai.config, "LLM_PLATFORM", "Ollama"):
            ai.get_ai_prompt_level1_for_original_conditions(["c"], big, "T-L1")
            ai.get_ai_prompt_oncotree_diagnoses_from_trial_info("x", big, "T-S2")
            ai.get_ai_prompt_child_values("c", big, "T-CH")
        warnings = " ".join(self._levels("WARNING"))
        for tid in ("T-L1", "T-S2", "T-CH"):
            self.assertIn(tid, warnings)
        self.assertEqual(ai.ENUM_CAP_EVENTS["dropped"], 3)


class TestStatusSchemas(unittest.TestCase):
    def test_receptor_values_match_what_the_mapper_keeps(self):
        # clinical_trials_gov filters on exactly these, so a value outside them
        # is silently discarded downstream; the enum stops it being generated.
        expected = ["Positive", "Negative", "Unknown", "!Positive", "!Negative"]
        for field in ("her2_status", "er_status", "pr_status"):
            self.assertEqual(ai.HER2_ER_PR_SCHEMA["properties"][field]["enum"],
                             expected, field)

    def test_mmr_fields_are_optional(self):
        # There is no "Unknown" for MMR, so requiring a field would force the
        # model to invent proficient or deficient.
        self.assertNotIn("required", ai.MMR_MS_SCHEMA)

    def test_either_age_bound_may_be_null(self):
        for end in ("minimum", "maximum"):
            bound = ai.AGE_BOUNDS_SCHEMA["properties"][end]
            self.assertIn("null", bound["properties"]["value"]["type"])

    def test_age_units_are_constrained_to_what_the_code_converts(self):
        from utils.age_bounds import UNIT_IN_YEARS
        unit = ai.AGE_BOUNDS_SCHEMA["properties"]["maximum"]["properties"]["unit"]
        self.assertEqual(set(unit["enum"]), set(UNIT_IN_YEARS))


if __name__ == '__main__':
    unittest.main()
