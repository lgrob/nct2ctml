"""
Roadmap 6.9: the mutation and CNV enrichment prompts carry a JSON schema, and
the enriched values are checked in code before they are merged.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.ai_helper as ai

logger.remove()

MUT = [{"genomic": {"hugo_symbol": "EGFR", "variant_category": "Mutation"}}]
CNV = [{"genomic": {"hugo_symbol": "MYCN", "variant_category": "Copy Number Variation"}}]


class TestSchemas(unittest.TestCase):

    def test_both_prompts_send_a_schema(self):
        schema, _ = ai.get_mutation_detail_enrichment_prompt(["EGFR"], "EGFR exon 19 deletion", MUT)
        self.assertIs(schema, ai.MUTATION_ENRICHMENT_SCHEMA)
        schema, _ = ai.get_cnv_detail_enrichment_prompt(["MYCN"], "MYCN amplification", CNV)
        self.assertIs(schema, ai.CNV_ENRICHMENT_SCHEMA)

    def test_schemas_are_valid_json_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        for schema in (ai.MUTATION_ENRICHMENT_SCHEMA, ai.CNV_ENRICHMENT_SCHEMA):
            jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate({"enriched_cnvs": [{"index": 0, "cnv_call": None}]}, ai.CNV_ENRICHMENT_SCHEMA)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"enriched_cnvs": [{"index": 0, "cnv_call": "Gain"}]}, ai.CNV_ENRICHMENT_SCHEMA)

    def test_schema_enums_match_what_the_prompt_lists(self):
        _, p = ai.get_mutation_detail_enrichment_prompt(["EGFR"], "x", MUT)
        self.assertTrue(all(f'"{v}"' in p for v in ai.VARIANT_CLASSIFICATIONS))
        _, p = ai.get_cnv_detail_enrichment_prompt(["MYCN"], "x", CNV)
        self.assertTrue(all(f'"{v}"' in p for v in ai.CNV_CALLS))


class TestMergeChecks(unittest.TestCase):

    def _mut(self, **kw):
        crit = [{"genomic": dict(MUT[0]["genomic"])}]
        ai.merge_enriched_criteria(crit, [dict(index=0, **kw)], "mutation")
        return crit[0]["genomic"]

    def _cnv(self, call):
        crit = [{"genomic": dict(CNV[0]["genomic"])}]
        ai.merge_enriched_criteria(crit, [{"index": 0, "cnv_call": call}], "cnv")
        return crit[0]["genomic"]

    def test_allowed_values_are_merged(self):
        g = self._mut(variant_classification="In_Frame_Del", exon=19)
        self.assertEqual((g["variant_classification"], g["exon"]), ("In_Frame_Del", 19))
        self.assertEqual(self._cnv("High Amplification")["cnv_call"], "High Amplification")

    def test_values_outside_the_lists_are_not_merged(self):
        g = self._mut(variant_classification="Deletion", exon="19")
        self.assertNotIn("variant_classification", g); self.assertNotIn("exon", g)
        for exon in (0, -3, True, 19.5):
            self.assertNotIn("exon", self._mut(variant_classification=None, exon=exon), exon)
        self.assertNotIn("cnv_call", self._cnv("Amplification"))

    def test_nulls_are_silent(self):
        before = len(ai.ENRICHMENT_REJECTED)
        g = self._mut(variant_classification=None, exon=None)
        self.assertEqual(g, MUT[0]["genomic"])
        self.assertEqual(len(ai.ENRICHMENT_REJECTED), before)


class TestAliasInContradictions(unittest.TestCase):

    def test_an_invented_inclusion_loses_to_an_exclusion_written_with_an_alias(self):
        # NCT04775485 (3.1 dry run after the NF-1 alias): the exclusion text says
        # "neurofibromatosis type 1 (NF-1)" and the inclusion prompt invented
        # an NF1 inclusion. Without the alias the exclusion text did not
        # "mention" NF1, so the invented inclusion was kept.
        from src.match_criteria_mapper import resolve_contradictory_genes
        inc = [{"genomic": {"hugo_symbol": "NF1", "variant_category": "Any Variation"}}]
        exc = [{"genomic": {"hugo_symbol": "NF1", "variant_category": "!Any Variation"}}]
        keep_inc, keep_exc, notes = resolve_contradictory_genes(
            inc, exc, "histopathologic verification of malignancy",
            "Known or suspected diagnosis of neurofibromatosis type 1 (NF-1)")
        self.assertEqual((keep_inc, keep_exc), ([], exc))
        self.assertEqual(notes, ["NF1: dropped fabricated inclusion"])


if __name__ == "__main__":
    unittest.main()
