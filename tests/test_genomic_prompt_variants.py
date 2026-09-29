"""Roadmap 2.9: inclusion genomic prompt variants (baseline unchanged)."""

import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.llm.prompts.genomic as genomic_prompts
import utils.llm.transport as transport
import utils.review.common as common
import utils.review.gate as gate

logger.remove()


def load(variant):
    """Reload config with this genomic prompt; None restores the default."""
    if variant is None:
        os.environ.pop("NCT2CTML_GENOMIC_PROMPT", None)
    else:
        os.environ["NCT2CTML_GENOMIC_PROMPT"] = variant
    import config

    # The prompts read config.GENOMIC_PROMPT when called, so reloading config
    # is enough; the platform in utils.llm.transport, and its offline guard,
    # are untouched.
    importlib.reload(config)


class TestGenomicPromptVariants(unittest.TestCase):
    def setUp(self):
        # These tests stub the model by assignment; put the real functions
        # back afterwards, or the stub answers every later test's call.
        for name in ("send_ai_request", "parse_ai_response"):
            self.addCleanup(setattr, transport, name, getattr(transport, name))

    def tearDown(self):
        # Until 2026-09-29 this reloaded with "baseline", which set the variable
        # again: every later test, and every subprocess they started, ran with
        # the baseline genomic prompt instead of the default.
        load(None)

    def test_baseline_has_no_rule_10_and_no_role(self):
        load("baseline")
        s, p = genomic_prompts.get_inclusion_genomic_criteria_prompt({"APC"}, "APC mutation")
        self.assertNotIn("10. ", p)
        self.assertNotIn("role", s["items"]["properties"]["genomic"]["properties"])

    def test_rules_and_roles_prompts(self):
        load("rules")
        s, p = genomic_prompts.get_inclusion_genomic_criteria_prompt({"APC"}, "APC mutation")
        self.assertIn("ENTRY REQUIREMENTS ONLY", p)
        load("roles")
        s, p = genomic_prompts.get_inclusion_genomic_criteria_prompt({"APC"}, "APC mutation")
        self.assertIn("role", s["items"]["properties"]["genomic"]["required"])

    def test_roles_keeps_only_requirements(self):
        load("roles")
        transport.send_ai_request = lambda i, p, s=None: [
            {
                "genomic": {
                    "hugo_symbol": "APC",
                    "variant_category": "Mutation",
                    "role": "cohort_specific",
                }
            },
            {
                "genomic": {
                    "hugo_symbol": "BRAF",
                    "variant_category": "Mutation",
                    "role": "requirement",
                }
            },
        ]
        transport.parse_ai_response = lambda r, trial_id="": r
        out = genomic_prompts.get_inclusion_genomic_criteria("T1", ["APC", "BRAF"], "text")
        self.assertEqual(
            [c["genomic"] for c in out], [{"hugo_symbol": "BRAF", "variant_category": "Mutation"}]
        )
        self.assertEqual(genomic_prompts.ROLE_DROPS.pop("T1"), [("APC", "cohort_specific")])

    def test_roles_union_keeps_cohort_union(self):
        load("roles_union")
        s, p = genomic_prompts.get_inclusion_genomic_criteria_prompt(
            {"ALK"}, "Stratum 1: ALK fusion"
        )
        self.assertIn(
            "cohort_union", s["items"]["properties"]["genomic"]["properties"]["role"]["enum"]
        )
        transport.send_ai_request = lambda i, p, s=None: [
            {
                "genomic": {
                    "hugo_symbol": "ALK",
                    "variant_category": "Structural Variation",
                    "role": "cohort_union",
                }
            },
            {
                "genomic": {
                    "hugo_symbol": "APC",
                    "variant_category": "Mutation",
                    "role": "cohort_specific",
                }
            },
        ]
        transport.parse_ai_response = lambda r, trial_id="": r
        out = genomic_prompts.get_inclusion_genomic_criteria("T2", ["ALK", "APC"], "text")
        self.assertEqual([c["genomic"]["hugo_symbol"] for c in out], ["ALK"])
        self.assertEqual(genomic_prompts.ROLE_DROPS.pop("T2"), [("APC", "cohort_specific")])


class TestGeneRoleDroppedIsInformation(unittest.TestCase):
    """Option A (user, 2026-09-28): genes kept out are published, not queued."""

    def _ctml(self):
        return {
            "gene_role_dropped": "FLT3 (cohort_specific)",
            "age": "Pediatric",
            "treatment_list": {
                "step": [
                    {
                        "match": [
                            {
                                "and": [
                                    {
                                        "clinical": {
                                            "oncotree_primary_diagnosis": "Acute Myeloid Leukemia",
                                            "age_numerical": "<22",
                                        }
                                    }
                                ]
                            }
                        ],
                        "arm": [{"arm_code": "A", "match": []}],
                    }
                ]
            },
        }

    def test_does_not_route_to_review(self):
        import tempfile

        from src.trial_map_manager import TrialMapManager

        d = tempfile.mkdtemp()
        self.assertFalse(
            TrialMapManager._destination_for(self._ctml(), d, "T3").endswith("needs-review")
        )

    def test_accept_does_not_refuse_it(self):
        import yaml

        self.assertNotIn("gene_role_dropped", common.FLAG_KEYS)
        c = self._ctml()
        self.assertFalse(
            [p for p in gate.problems(c, yaml.safe_dump(c)) if "gene_role_dropped" in p]
        )

    def test_index_publishes_genes_not_required(self):
        import utils.build_trial_index as b

        self.assertIn("genes_not_required", b.TRIAL_COLUMNS)


class TestRoleDropsReachTheTrial(unittest.TestCase):
    """
    The genes the roles prompt keeps out of the tree reach the mapped trial as
    gene_role_dropped (published as genes_not_required). Moving ROLE_DROPS in
    step 11 briefly broke this: the mapper checked hasattr(ai_helper,
    "ROLE_DROPS"), which was then always False, and dropped every record.
    """

    def test_recorded_drops_are_written_once_each(self):
        from src.trial_map_manager import TrialMapManager

        genomic_prompts.ROLE_DROPS["T9"] = [
            ("FLT3", "cohort_specific"),
            ("BCR", "example"),
            ("FLT3", "cohort_specific"),
        ]
        ctml = {"nct_id": "T9"}
        TrialMapManager._record_role_drops(ctml, "T9")
        self.assertEqual(ctml["gene_role_dropped"], "FLT3 (cohort_specific); BCR (example)")
        self.assertNotIn("T9", genomic_prompts.ROLE_DROPS)

    def test_no_drops_writes_nothing(self):
        from src.trial_map_manager import TrialMapManager

        ctml = {"nct_id": "T10"}
        TrialMapManager._record_role_drops(ctml, "T10")
        self.assertNotIn("gene_role_dropped", ctml)


if __name__ == "__main__":
    unittest.main()
