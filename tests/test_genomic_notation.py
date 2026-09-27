"""H3C3 beside H3C2; rearranged-only genes as Structural Variation; ARM1 is not a gene (2026-09-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import src.match_criteria_mapper as mcm
import src.trial_config as tc
import utils.review_helper as rh

logger.remove()


class TestGenomicNotation(unittest.TestCase):

    def test_h3_keyword_includes_h3c3(self):
        self.assertIn("H3C3", tc.contextual_gene_synonyms["H3"][1])

    def test_arm_labels_are_blocked(self):
        self.assertIn("ARM1", tc.blocked_gene_synonyms)

    def test_rearranged_only(self):
        self.assertTrue(mcm.is_rearrangement_only("KMT2A", "Presence of KMT2A rearrangement or NPM1 mutation"))
        self.assertTrue(mcm.is_rearrangement_only("KMT2A", "Presence of KMT2Ar, NUP98r, NPM1c or UBTF-ITD"))
        for text in ("EPOR: truncating rearrangements or mutations in exon 8, EPOR fusions",
                     "KMT2A, NPM1 or nucleoporin alterations. AML harboring KMT2A-r",
                     "BRAF fusion or BRAF V600E", "KMT2A rearranged or KMT2A-PTD mutated"):
            self.assertFalse(mcm.is_rearrangement_only(text.split()[0].strip(":,") if not text.startswith("KMT2A,") else "KMT2A", text), text)

    def test_negated_stays_negated(self):
        c = [{"genomic": {"hugo_symbol": "ABL1", "variant_category": "!Any Variation"}}]
        mcm.rearranged_as_structural(c, "Ph-like ALL (without targetable ABL1 fusion)")
        self.assertEqual(c[0]["genomic"]["variant_category"], "!Structural Variation")

    def test_sibling_gene(self):
        t = {"and": [{"genomic": {"hugo_symbol": "H3C2", "variant_category": "!Any Variation"}},
                     {"or": [{"genomic": {"hugo_symbol": "H3C2", "variant_category": "Mutation", "protein_change": "p.K27M"}}]}]}
        self.assertEqual(rh.add_sibling_gene(t, "H3C2", "H3C3"), 2)
        self.assertEqual([n["genomic"]["hugo_symbol"] for n in t["and"][:2]], ["H3C2", "H3C3"])
        self.assertEqual([n["genomic"]["hugo_symbol"] for n in t["and"][2]["or"]], ["H3C2", "H3C3"])


if __name__ == "__main__":
    unittest.main()
