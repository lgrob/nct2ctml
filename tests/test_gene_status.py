"""gene_status_contradiction: genes required although the text says absent or irrelevant (2026-09-27)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import src.text_rules as text_rules
import utils.review.common as common

logger.remove()


def tree(*genomic):
    return {
        "treatment_list": {
            "step": [{"match": [{"and": [{"or": [{"genomic": g} for g in genomic]}]}]}]
        }
    }


class TestGeneStatus(unittest.TestCase):
    def test_wild_type_read_as_mutation_is_found(self):
        # NCT05805605, the case the user reported.
        t = tree(
            {"hugo_symbol": "NPM1", "variant_category": "Mutation"},
            {"hugo_symbol": "FLT3", "variant_category": "Mutation"},
        )
        inc = "Normal karyotype with mutated NPM1 and wild type FLT-ITD (unless persistently NPM1 positive by PCR)"
        self.assertEqual(set(text_rules.gene_status_contradictions(t, inc)), {"FLT3"})

    def test_negative_and_no_known_mutation(self):
        self.assertIn(
            "ERBB2",
            text_rules.gene_status_contradictions(
                tree({"hugo_symbol": "ERBB2", "variant_category": "Any Variation"}),
                "ER < 10%, PR < 10%, and HER2 negative",
            ),
        )
        self.assertIn(
            "EGFR",
            text_rules.gene_status_contradictions(
                tree({"hugo_symbol": "EGFR", "variant_category": "Any Variation"}),
                "NSCLC with no known EGFR or ALK positive tumor mutations",
            ),
        )

    def test_status_that_does_not_matter(self):
        t = tree(
            {"hugo_symbol": "BRAF", "variant_category": "Mutation", "protein_change": "p.V600E"}
        )
        self.assertIn(
            "BRAF",
            text_rules.gene_status_contradictions(
                t, "Melanoma can be of either mutant or wild-type B-RAF."
            ),
        )
        t = tree({"hugo_symbol": "NPM1", "variant_category": "Any Variation"})
        self.assertIn(
            "NPM1",
            text_rules.gene_status_contradictions(
                t, "FLT3-ITD mutation with or without NPM1 mutation"
            ),
        )

    def test_two_stated_routes_are_not_flagged(self):
        t = tree(
            {
                "hugo_symbol": "MYCN",
                "variant_category": "Copy Number Variation",
                "cnv_call": "High Amplification",
            }
        )
        inc = "stage 4 with MYCN amplification, or stage 4 without MYCN amplification aged > 12 months"
        self.assertEqual(text_rules.gene_status_contradictions(t, inc), {})

    def test_a_negated_criterion_is_not_a_requirement(self):
        t = tree(
            {
                "hugo_symbol": "CDKN2A",
                "variant_category": "Copy Number Variation",
                "cnv_call": "!Homozygous Deletion",
            },
            {"hugo_symbol": "KIT", "variant_category": "!Mutation"},
        )
        self.assertEqual(
            text_rules.gene_status_contradictions(
                t, "Absence of CDKN2A/B homozygous deletion; without cKIT mutation"
            ),
            {},
        )

    def test_a_positive_requirement_is_not_flagged(self):
        t = tree({"hugo_symbol": "ALK", "variant_category": "Mutation"})
        self.assertEqual(
            text_rules.gene_status_contradictions(t, "Neuroblastoma with an ALK mutation"), {}
        )

    def test_known_false_alarm_is_documented(self):
        # 2023-503322-39-00: the EWSR1-positive route is only implied ("genetically
        # confirmed Ewing sarcoma"), so the check flags it; a curator clears it.
        t = tree({"hugo_symbol": "EWSR1", "variant_category": "Structural Variation"})
        inc = "genetically confirmed Ewing sarcoma, or round cell sarcomas which are Ewing's-like but negative for EWSR1 gene rearrangement"
        self.assertIn("EWSR1", text_rules.gene_status_contradictions(t, inc))

    def test_accept_refuses_the_flag(self):
        self.assertIn("gene_status_contradiction", common.FLAG_KEYS)


if __name__ == "__main__":
    unittest.main()
