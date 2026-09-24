import os
import sys
import unittest

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
        schema = ai.oncotree_diagnoses_schema([f"Term {i}" for i in range(500)])
        items = schema["properties"]["oncotree_diagnoses"]["items"]
        self.assertNotIn("enum", items)
        self.assertEqual(items["type"], "string")

    def test_an_empty_candidate_list_is_not_an_empty_enum(self):
        # An empty enum would make every answer invalid.
        items = ai.oncotree_diagnoses_schema([])["properties"]["oncotree_diagnoses"]["items"]
        self.assertNotIn("enum", items)


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
