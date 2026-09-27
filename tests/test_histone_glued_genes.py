"""
Histone protein names and genes glued to a protein change count as the text
naming the gene - in the scan, in the mapper's text checks and on the review
sheet alike.

NCT07306299 writes "H3.3K27M, H3.1K27M, H3.3G34R, BRAF V600E, PIK3CA H1047R,
IDH1 R132H, or EGFRvIII"; H3-3A, H3C2 and EGFR were flagged gene_unsupported
although the text names all three. The negative cases are the ones that must
never become support: an arbitrary letter run after a gene (CD19CAR, IL2RA),
and the H3 K27-altered diagnosis, which includes tumours with no H3 mutation
(2023-508617-16-00 writes "DMG-H3K27a").
"""
import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import utils.gene_mentions as gm
import utils.reference_validation as rv
import utils.review_helper as rh
from src.match_criteria_mapper import _flag_unsupported_genes, _text_mentions_gene
from src.trial_criteria_to_genes import TrialCriteriaToGenes

logger.remove()

NCT07306299 = ("IV glioma harboring one or more of the following mutations: H3.3K27M, H3.1K27M, "
               "H3.3G34R, BRAF V600E, PIK3CA H1047R, IDH1 R132H, or EGFRvIII.")

H3_ALTERED = ["DMG-H3K27a", "diffuse midline glioma, H3K27-altered", "H3K27me3 loss",
              "loss of H3K28 trimethylation together with EZHIP overexpression", "EZHIP positive"]


def scan(text):
    return TrialCriteriaToGenes(text, rv.gene_synonym_mapping()).extract_official_gene_symbols()


def flagged(gene, text):
    crit = [{"genomic": {"hugo_symbol": gene, "variant_category": "Mutation"}}]
    _flag_unsupported_genes(crit, scan(text), text)
    return crit[0]["genomic"].get("gene_unsupported")


class TestCuratedHistoneAliases(unittest.TestCase):

    def test_addendum_rows(self):
        rows = {r[0]: r[1] for r in csv.reader(open(config.GENE_SYNONYM_ADDENDUM_FILE_PATH), delimiter="\t")
                if len(r) >= 2}
        self.assertEqual(rows["H3.3"], "H3-3A,H3-3B")
        self.assertEqual(rows["H3.1"], "H3C2,H3C3")

    def test_addendum_wins_over_the_ncbi_collision(self):
        # NCBI gives H3.1 to H3C3 and H3C6 (ref/synonym_collisions.tsv); the
        # addendum means the H3.1 genes where K27M occurs.
        self.assertEqual(rv.gene_synonym_mapping()["H3.1"], ["H3C2,H3C3"])
        self.assertEqual(scan("H3.1 K27M"), ["H3C2", "H3C3"])
        self.assertTrue(_text_mentions_gene("H3.1 K27M", "H3C3"))
        self.assertFalse(_text_mentions_gene("H3.1 K27M", "H3C6"))
        ref = rh.Reference()
        self.assertIn("H3.1", ref.gene_terms("H3C2"))
        self.assertNotIn("H3.1", ref.gene_terms("H3C6"))

    def test_bare_h33(self):
        self.assertEqual(scan("H3.3 G34R"), ["H3-3A", "H3-3B"])
        self.assertTrue(_text_mentions_gene("H3.3 mutant", "H3-3B"))

    def test_multi_gene_rows_are_not_rewrites(self):
        # A family name names every gene of the row, but is not one gene.
        self.assertIsNone(rv.canonical_gene("H3.1"))
        self.assertIsNone(rv.canonical_gene("H3.3"))
        self.assertIn("H3.3", rv.curated_group_aliases()["H3-3A"])
        self.assertNotIn("H3-3A", rv.curated_aliases())


class TestGluedChange(unittest.TestCase):

    def test_split(self):
        for token, head in [("H3.3K27M", "H3.3"), ("BRAFV600E", "BRAF"), ("KRASG12C", "KRAS"),
                            ("IDH1R132H", "IDH1"), ("PIK3CAH1047R", "PIK3CA"), ("BRAFp.V600E", "BRAF"),
                            ("NRASQ61*", "NRAS"), ("TP53R213X", "TP53"), ("EGFRvIII", "EGFR"),
                            ("EGFRvII", "EGFR"), ("EGFRvIV", "EGFR")]:
            self.assertEqual(gm.split_glued(token), head, token)

    def test_no_split_of_a_letter_run(self):
        for token in ["CD19CAR", "IL2RA", "H3K27a", "H3K27me3", "BRAFv600", "KITvIII", "B7H3"]:
            self.assertIsNone(gm.split_glued(token), token)

    def test_a_gene_name_is_never_split(self):
        # split_glued is syntactic ("CDKN2A" -> "CDK"); the scan refuses to
        # split a token that is itself a gene name. Measured on the current
        # ref files, no name in the synonym table splits into a head that
        # the scan would accept as another gene.
        self.assertEqual(scan("CDKN2A, KMT2A, DNMT3A, KDM6A deletion"),
                         ["CDKN2A", "DNMT3A", "KDM6A", "KMT2A"])
        mapping = rv.gene_synonym_mapping()
        official = {s for v in mapping.values() for x in v for s in x.split(",")}
        clashes = [(y, h) for y in mapping for h in [gm.split_glued(y)]
                   if h and h in mapping and (len(h) > 3 or h in official)]
        self.assertEqual(clashes, [])

    def test_scan_nct07306299(self):
        self.assertEqual(scan(NCT07306299),
                         ["BRAF", "EGFR", "H3-3A", "H3-3B", "H3C2", "H3C3", "IDH1", "PIK3CA"])

    def test_scan_glued(self):
        self.assertEqual(scan("KRASG12C or BRAFV600E"), ["BRAF", "KRAS"])
        self.assertEqual(scan("EGFRvIII-positive"), ["EGFR"])

    def test_scan_negative(self):
        self.assertEqual(scan("CD19CAR T cells"), [])
        self.assertNotIn("IL2", scan("IL2RA"))
        self.assertNotIn("CD19", scan("anti-CD19CAR"))

    def test_text_mentions(self):
        self.assertTrue(_text_mentions_gene(NCT07306299, "EGFR"))
        self.assertTrue(_text_mentions_gene(NCT07306299, "H3-3A"))
        self.assertTrue(_text_mentions_gene("BRAFV600E", "BRAF"))
        self.assertFalse(_text_mentions_gene("CD19CAR", "CD19"))
        self.assertFalse(_text_mentions_gene("IL2RA", "IL2"))
        self.assertFalse(_text_mentions_gene("KITvIII", "KIT"))

    def test_flag(self):
        for gene in ("H3-3A", "H3C2", "EGFR"):
            self.assertIsNone(flagged(gene, NCT07306299), gene)
        self.assertEqual(flagged("CD19", "CD19CAR T cells"), "CD19")


class TestHistoneVariants(unittest.TestCase):

    def test_mutation_forms(self):
        for text in ["H3K27M", "H3 K27M", "H3-K27M", "H3K28M", "H3K27I mutation", "H3K27M-mutant"]:
            self.assertEqual(gm.histone_variant_genes(text), ["H3-3A", "H3-3B", "H3C2", "H3C3"], text)
        for text in ["H3G34R/V", "H3 G34R", "H3G34-mutant", "H3G34 (R/V) mutation", "H3G35R"]:
            self.assertEqual(gm.histone_variant_genes(text), ["H3-3A", "H3-3B"], text)

    def test_altered_is_not_a_mutation(self):
        for text in H3_ALTERED + ["H3 K27-altered", "H3K27-altered", "H3 K27me3", "H3K28me3"]:
            self.assertEqual(gm.histone_variant_genes(text), [], text)
            self.assertFalse(_text_mentions_gene(text, "H3-3A"), text)

    def test_altered_is_not_support_for_a_mutation(self):
        for text in H3_ALTERED:
            self.assertEqual(flagged("H3-3A", text), "H3-3A", text)

    def test_known_gap_standalone_h3_token(self):
        # Not changed here: the contextual rule for the blocked alias "H3"
        # (src/trial_config.contextual_gene_synonyms) resolves a standalone
        # "H3" whenever the text contains "k27", so "H3 K27-altered" (with a
        # space) still reaches the scan as H3-3A/H3-3B/H3C2, as it did before
        # this change. The glued "H3K27-altered" does not. H3C3 (H3.1) was
        # added to that rule on 2026-09-27 (it carries K27M as H3C2 does).
        self.assertEqual(scan("H3 K27-altered"), ["H3-3A", "H3-3B", "H3C2", "H3C3"])
        self.assertEqual(scan("H3K27-altered"), [])

    def test_g34_is_not_h31(self):
        self.assertFalse(_text_mentions_gene("H3G34R", "H3C2"))
        self.assertEqual(flagged("H3C2", "H3G34R"), "H3C2")

    def test_mutation_is_support(self):
        # NCT04196413, NCT05476939, NCT05843253
        self.assertIsNone(flagged("H3C2", "H3K27M or H3K27I mutation. Confirmed by CLIA test."))
        self.assertIsNone(flagged("H3C3", "Histological diagnosis of DIPG (i.e. H3K28M or EZHIP positive"))
        self.assertIsNone(flagged("H3-3A", "For Stratum E: H3G34 (R/V) mutation"))

    def test_gene_family_only(self):
        self.assertNotIn("H3C6", scan("H3K27M"))
        self.assertFalse(_text_mentions_gene("H3K27M", "H3C14"))


class TestReviewSheetAgrees(unittest.TestCase):

    def setUp(self):
        self.ref = rh.Reference()

    def ev(self, text, gene):
        return rh.evidence([("inclusion", text)], self.ref.gene_terms(gene), gene=gene)

    def test_glued_and_histone_evidence(self):
        self.assertTrue(self.ev(NCT07306299, "H3-3A"))
        self.assertTrue(self.ev(NCT07306299, "H3C2"))
        self.assertTrue(self.ev(NCT07306299, "EGFR"))
        self.assertTrue(self.ev("H3K28M or EZHIP positive", "H3C3"))

    def test_negative_evidence(self):
        self.assertFalse(self.ev("CD19CAR T cells", "CD19"))
        for text in H3_ALTERED:
            self.assertFalse(self.ev(text, "H3-3A"), text)

    def test_plain_evidence_unchanged(self):
        self.assertEqual(rh.find_mentions("BRAFV600E", {"BRAF"}), [])
        self.assertEqual(rh.find_mentions("BRAFV600E", {"BRAF"}, gene="BRAF"), [(0, 4, "BRAF")])


if __name__ == "__main__":
    unittest.main()
