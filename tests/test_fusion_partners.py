"""
Fusion partners: validated when the mapper receives them, published in the
index from both genes' sides.
"""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.ai_helper as ai
import utils.reference_validation as rv
from src.match_criteria_mapper import _clean_fusion_partners
from utils.build_trial_index import build

logger.remove()


def _sv(gene, partner, category="Structural Variation"):
    return [{"genomic": {"hugo_symbol": gene, "variant_category": category,
                         "fusion_partner": partner}}]


class TestResolver(unittest.TestCase):

    def test_panel_off_panel_and_locus(self):
        self.assertEqual(rv.fusion_partner("FLI1"), ("FLI1", "panel"))
        self.assertEqual(rv.fusion_partner("RUNX1T1"), ("RUNX1T1", "off_panel"))
        self.assertEqual(rv.fusion_partner("IGH"), ("IGH", "locus"))

    def test_an_off_panel_alias_is_not_guessed(self):
        # "CAR" is an alias of PRKAR1A; in trial text it means CAR-T.
        self.assertEqual(rv.fusion_partner("CAR"), (None, "unknown"))
        self.assertEqual(rv.fusion_partner("ETO"), (None, "unknown"))


class TestMapperCheck(unittest.TestCase):

    def test_a_valid_partner_is_kept(self):
        g = _clean_fusion_partners(_sv("EWSR1", "FLI1"))[0]["genomic"]
        self.assertEqual(g["fusion_partner"], "FLI1")

    def test_an_unknown_partner_is_kept_visible_not_silently_used(self):
        g = _clean_fusion_partners(_sv("RUNX1", "ETO"))[0]["genomic"]
        self.assertNotIn("fusion_partner", g)
        self.assertEqual(g["fusion_partner_unverified"], "ETO")

    def test_a_partner_on_a_mutation_is_rejected(self):
        g = _clean_fusion_partners(_sv("BRAF", "KIAA1549", "Mutation"))[0]["genomic"]
        self.assertNotIn("fusion_partner", g)

    def test_the_gene_cannot_be_its_own_partner(self):
        g = _clean_fusion_partners(_sv("KMT2A", "KMT2A"))[0]["genomic"]
        self.assertNotIn("fusion_partner", g)

    def test_null_partner_is_dropped_quietly(self):
        g = _clean_fusion_partners(_sv("NTRK1", None))[0]["genomic"]
        self.assertEqual(set(g), {"hugo_symbol", "variant_category"})

    def test_an_off_panel_first_gene_is_swapped_before_the_panel_filter(self):
        from src.match_criteria_mapper import _postprocess_genomic_criteria
        g = _postprocess_genomic_criteria(_sv("USP9X", "DDX3X"), "NCT05745714")
        self.assertEqual([(x["genomic"]["hugo_symbol"], x["genomic"]["fusion_partner"]) for x in g],
                         [("DDX3X", "USP9X")])

    def test_b7h3_expression_is_not_a_genomic_criterion(self):
        from src.match_criteria_mapper import _postprocess_genomic_criteria
        g = _postprocess_genomic_criteria(
            [{"genomic": {"hugo_symbol": "CD276", "variant_category": "Any Variation"}}], "NCT04897321")
        self.assertEqual(g, [])

    def test_the_model_can_say_it(self):
        # llama.cpp builds its grammar from declared properties.
        props = ai.GENOMIC_CRITERIA_SCHEMA["items"]["properties"]["genomic"]["properties"]
        self.assertIn("fusion_partner", props)


class TestIndex(unittest.TestCase):

    def _rows(self, genomic):
        source, out = tempfile.mkdtemp(), tempfile.mkdtemp()
        doc = {"nct_id": "NCT1", "treatment_list": {"step": [{"match": [{"and": [
            {"clinical": {"oncotree_primary_diagnosis": "Ewing Sarcoma"}},
            {"genomic": genomic}]}]}]}}
        with open(os.path.join(source, "NCT1.json"), "w") as handle:
            json.dump(doc, handle)
        build(source, out)
        with open(os.path.join(out, "trial_genomic.tsv")) as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_a_panel_pair_is_indexed_from_both_sides(self):
        rows = self._rows({"hugo_symbol": "EWSR1", "variant_category": "Structural Variation",
                           "fusion_partner": "FLI1"})
        self.assertEqual({(r["hugo_symbol"], r["fusion_partner"]) for r in rows},
                         {("EWSR1", "FLI1"), ("FLI1", "EWSR1")})
        self.assertEqual({r["fusion"] for r in rows}, {"EWSR1::FLI1"})

    def test_an_off_panel_partner_is_indexed_from_the_panel_side_only(self):
        rows = self._rows({"hugo_symbol": "RUNX1", "variant_category": "Structural Variation",
                           "fusion_partner": "RUNX1T1"})
        self.assertEqual([(r["hugo_symbol"], r["fusion"], r["fusion_partner_check"]) for r in rows],
                         [("RUNX1", "RUNX1::RUNX1T1", "off_panel")])

    def test_no_partner_means_any_fusion(self):
        rows = self._rows({"hugo_symbol": "NTRK1", "variant_category": "Structural Variation"})
        self.assertEqual((rows[0]["fusion_partner"], rows[0]["fusion"]), ("", ""))

    def test_an_unverified_partner_is_reported(self):
        rows = self._rows({"hugo_symbol": "RUNX1", "variant_category": "Structural Variation",
                           "fusion_partner_unverified": "ETO"})
        self.assertEqual(rows[0]["fusion_partner_check"], "unverified: ETO")


if __name__ == "__main__":
    unittest.main()
