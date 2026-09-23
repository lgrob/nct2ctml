"""
Trial protein changes rewritten as HGVS and checked against the MANE Select
protein. Every assertion about a residue is checked against the committed
reference file, not typed from memory.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import utils.protein_change as pc


class TestNotation(unittest.TestCase):

    def check(self, gene, stated, hgvs, kind=None):
        r = pc.normalise(gene, stated)
        self.assertEqual(r.status, pc.VERIFIED, f"{gene} {stated}: {r.status} {r.detail}")
        self.assertEqual(r.hgvs, hgvs)
        if kind:
            self.assertEqual(r.kind, kind)
        return r

    def test_one_letter_substitution(self):
        r = self.check("BRAF", "p.V600E", "p.Val600Glu", "substitution")
        # The accessions VEP reports as CSQ_MANE_SELECT / CSQ_HGVSp.
        self.assertTrue(r.refseq_protein.startswith("NP_004324"))
        self.assertTrue(r.ensembl_protein.startswith("ENSP00000493543"))

    def test_spellings_converge(self):
        for stated in ("V600E", "p.V600E", "p.Val600Glu", "Val600Glu", "p.(Val600Glu)", "p.(V600E)"):
            self.check("BRAF", stated, "p.Val600Glu")

    def test_kras_g12c(self):
        self.check("KRAS", "G12C", "p.Gly12Cys")

    def test_nonsense(self):
        self.check("TP53", "R213*", "p.Arg213Ter", "nonsense")
        self.check("TP53", "p.Arg213Ter", "p.Arg213Ter", "nonsense")

    def test_egfr_exon19_deletion_range(self):
        self.check("EGFR", "E746_A750del", "p.Glu746_Ala750del", "deletion")

    def test_egfr_insertion(self):
        self.check("EGFR", "p.H773_V774insH", "p.His773_Val774insHis", "insertion")

    def test_wildcard_keeps_the_repo_convention(self):
        self.check("EGFR", "G719X", "p.Gly719", "any_substitution")
        self.check("BRAF", "V600", "p.Val600", "any_change")

    def test_frameshift_short_form(self):
        self.check("APC", "R1450fs", "p.Arg1450fs", "frameshift")


class TestHistoneNumbering(unittest.TestCase):
    """
    Histone literature numbers the mature protein, without the initiator
    methionine. Diffuse midline glioma's K27M is p.Lys28Met in HGVS.
    """

    def test_k27m_is_lys28met_on_every_h3_gene_the_trials_use(self):
        for gene in ("H3-3A", "H3-3B", "H3C2"):
            r = pc.normalise(gene, "p.K27M")
            self.assertEqual(r.status, pc.VERIFIED, r.detail)
            self.assertEqual(r.hgvs, "p.Lys28Met")
            self.assertEqual(r.numbering, "histone_mature")

    def test_g34r(self):
        self.assertEqual(pc.normalise("H3-3A", "G34R").hgvs, "p.Gly35Arg")

    def test_an_hgvs_h3_change_is_not_shifted_twice(self):
        r = pc.normalise("H3-3A", "p.Lys28Met")
        self.assertEqual((r.status, r.hgvs, r.numbering), (pc.VERIFIED, "p.Lys28Met", "hgvs"))

    def test_the_shift_is_decided_by_sequence_not_by_name(self):
        _, _, sequence = pc.load_reference()["H3-3A"]
        self.assertTrue(pc._is_histone_h3(sequence))
        self.assertFalse(pc._is_histone_h3(pc.load_reference()["BRAF"][2]))

    def test_every_h3_gene_in_the_reference_is_recognised(self):
        ref = pc.load_reference()
        named = {g for g in ref if g.startswith(("H3-", "H3C"))}
        by_sequence = {g for g, (_, _, seq) in ref.items() if pc._is_histone_h3(seq)}
        # Centromeric/testis variants (H3-5, H3-7...) may diverge; report them.
        self.assertTrue({"H3-3A", "H3-3B", "H3C2"} <= by_sequence)
        self.assertTrue(by_sequence <= named, by_sequence - named)


class TestRejections(unittest.TestCase):
    """A change that names the wrong residue describes a different variant."""

    def test_wrong_reference_residue(self):
        r = pc.normalise("BRAF", "p.V601E")
        self.assertEqual(r.status, "reference_mismatch")
        self.assertEqual(r.hgvs, "")
        self.assertIn("Val601", r.detail)

    def test_h3_hgvs_numbering_written_one_letter_is_caught(self):
        # "K28M" in one-letter is mature numbering -> residue 29, which is not Lys.
        self.assertEqual(pc.normalise("H3-3A", "K28M").status, "reference_mismatch")

    def test_out_of_range(self):
        self.assertEqual(pc.normalise("KRAS", "G1200C").status, "position_out_of_range")

    def test_backwards_range(self):
        self.assertEqual(pc.normalise("EGFR", "A750_E746del").status, "invalid_range")

    def test_non_adjacent_insertion_flanks(self):
        self.assertEqual(pc.normalise("EGFR", "H773_D770insH").status, "invalid_range")

    def test_unparsed_is_never_guessed(self):
        for stated in ("V600E/K", "exon 19 deletion", "V600EK", "p.V600Z", "600E"):
            r = pc.normalise("BRAF", stated)
            self.assertEqual((r.status, r.hgvs), ("unparsed", ""), stated)

    def test_gene_without_reference(self):
        self.assertEqual(pc.normalise("MUC1", "P100L").status, "no_reference")

    def test_empty(self):
        self.assertEqual(pc.normalise("BRAF", "").status, "empty")


if __name__ == "__main__":
    unittest.main()
