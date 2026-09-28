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


    def test_roles_union_keeps_cohort_union(self):
        ai = load("roles_union")
        s, p = ai.get_inclusion_genomic_criteria_prompt({"ALK"}, "Stratum 1: ALK fusion")
        self.assertIn("cohort_union", s["items"]["properties"]["genomic"]["properties"]["role"]["enum"])
        ai.send_ai_request = lambda i, p, s=None: [
            {"genomic": {"hugo_symbol": "ALK", "variant_category": "Structural Variation", "role": "cohort_union"}},
            {"genomic": {"hugo_symbol": "APC", "variant_category": "Mutation", "role": "cohort_specific"}}]
        ai.parse_ai_response = lambda r, trial_id="": r
        out = ai.get_inclusion_genomic_criteria("T2", ["ALK", "APC"], "text")
        self.assertEqual([c["genomic"]["hugo_symbol"] for c in out], ["ALK"])
        self.assertEqual(ai.ROLE_DROPS.pop("T2"), [("APC", "cohort_specific")])


if __name__ == "__main__":
    unittest.main()


class TestGeneRoleDroppedIsInformation(unittest.TestCase):
    """Option A (user, 2026-09-28): genes kept out are published, not queued."""

    def _ctml(self):
        return {"gene_role_dropped": "FLT3 (cohort_specific)", "age": "Pediatric",
                "treatment_list": {"step": [{"match": [{"and": [
                    {"clinical": {"oncotree_primary_diagnosis": "Acute Myeloid Leukemia", "age_numerical": "<22"}}]}],
                    "arm": [{"arm_code": "A", "match": []}]}]}}

    def test_does_not_route_to_review(self):
        import tempfile
        from src.trial_map_manager import TrialMapManager
        d = tempfile.mkdtemp()
        self.assertFalse(TrialMapManager._destination_for(self._ctml(), d, "T3").endswith("needs-review"))

    def test_accept_does_not_refuse_it(self):
        import yaml
        import utils.review_helper as rh
        self.assertNotIn("gene_role_dropped", rh.FLAG_KEYS)
        c = self._ctml()
        self.assertFalse([p for p in rh.problems(c, yaml.safe_dump(c)) if "gene_role_dropped" in p])

    def test_index_publishes_genes_not_required(self):
        import utils.build_trial_index as b
        self.assertIn("genes_not_required", b.TRIAL_COLUMNS)
