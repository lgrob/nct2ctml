"""Roadmap 2.9: inclusion genomic prompt variants (baseline unchanged)."""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

logger.remove()


def load(variant):
    os.environ["NCT2CTML_GENOMIC_PROMPT"] = variant
    import config
    import utils.ai_helper as ai
    importlib.reload(config)
    return importlib.reload(ai)


class TestGenomicPromptVariants(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("NCT2CTML_GENOMIC_PROMPT", None)
        load("baseline")

    def test_baseline_has_no_rule_10_and_no_role(self):
        ai = load("baseline")
        s, p = ai.get_inclusion_genomic_criteria_prompt({"APC"}, "APC mutation")
        self.assertNotIn("10. ", p)
        self.assertNotIn("role", s["items"]["properties"]["genomic"]["properties"])

    def test_rules_and_roles_prompts(self):
        ai = load("rules")
        s, p = ai.get_inclusion_genomic_criteria_prompt({"APC"}, "APC mutation")
        self.assertIn("ENTRY REQUIREMENTS ONLY", p)
        ai = load("roles")
        s, p = ai.get_inclusion_genomic_criteria_prompt({"APC"}, "APC mutation")
        self.assertIn("role", s["items"]["properties"]["genomic"]["required"])

    def test_roles_keeps_only_requirements(self):
        ai = load("roles")
        ai.send_ai_request = lambda i, p, s=None: [
            {"genomic": {"hugo_symbol": "APC", "variant_category": "Mutation", "role": "cohort_specific"}},
            {"genomic": {"hugo_symbol": "BRAF", "variant_category": "Mutation", "role": "requirement"}}]
        ai.parse_ai_response = lambda r, trial_id="": r
        out = ai.get_inclusion_genomic_criteria("T1", ["APC", "BRAF"], "text")
        self.assertEqual([c["genomic"] for c in out], [{"hugo_symbol": "BRAF", "variant_category": "Mutation"}])
        self.assertEqual(ai.ROLE_DROPS.pop("T1"), [("APC", "cohort_specific")])


if __name__ == "__main__":
    unittest.main()
