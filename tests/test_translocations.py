"""
Cytogenetic notation -> gene pairs, by the curated table only. Cases are
strings from cached trial texts.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.reference_validation as rv
import utils.translocations as tl

logger.remove()


def one(text):
    found = tl.find(text)
    assert len(found) == 1, (text, found)
    return tl.resolve(found[0])


class TestTable(unittest.TestCase):

    def test_every_gene_is_a_current_symbol_or_locus(self):
        for notation, rows in tl.table().items():
            for _, a, b, _ in rows:
                for gene in (a, b):
                    if gene:
                        self.assertEqual(rv.fusion_partner(gene)[0], gene, (notation, gene))

    def test_every_row_has_a_reason(self):
        for rows in tl.table().values():
            for row in rows:
                self.assertTrue(row[3])


class TestParsing(unittest.TestCase):

    def test_spacing_colon_and_comma_variants(self):
        for text in ("t(9;22)", "t (9; 22)", "t(9:22)", "t(9,22)"):
            self.assertEqual(tl.find(text)[0].notation, "t(9;22)", text)

    def test_bands_are_read_at_major_band(self):
        self.assertEqual(tl.find("t(9;22)(q34;q11.2)")[0].bands, ("q34", "q11"))
        self.assertEqual(tl.find("t(10;11)(p13;q14-21)")[0].bands, ("p13", "q14"))
        self.assertEqual(tl.find("inv(3)(q21.3q26.2)")[0].bands, ("q21", "q26"))

    def test_spaced_bands_as_written_in_ncT06083883(self):
        self.assertEqual(tl.find("t(12; 22) (q13;q12)")[0].bands, ("q13", "q12"))

    def test_chromosome_order_is_canonical(self):
        self.assertEqual(tl.find("t(22;9)")[0].notation, "t(9;22)")
        self.assertEqual(tl.find("t (X; 18)")[0].notation, "t(X;18)")

    def test_words_are_not_rearrangements(self):
        self.assertEqual(tl.find("at(9;22) is not; test(1;2); t(9)"), [])


class TestResolution(unittest.TestCase):

    def test_bands_decide_inv16(self):
        self.assertEqual((one("inv(16)(p13.1q22)").gene_a, one("inv(16)(p13.1q22)").gene_b), ("CBFB", "MYH11"))
        self.assertEqual((one("inv(16)(p13.3q24.3)").gene_a, one("inv(16)(p13.3q24.3)").gene_b), ("CBFA2T3", "GLIS2"))

    def test_bare_form_takes_the_single_conventional_row(self):
        r = one("inv(16)")
        self.assertEqual((r.gene_a, r.gene_b, r.status), ("CBFB", "MYH11", "resolved"))

    def test_ambiguous_bare_form_gives_only_the_shared_gene(self):
        r = one("t(8;14)")
        self.assertEqual((r.gene_a, r.gene_b, r.status), ("MYC", "", "gene_level"))
        self.assertEqual((one("t (8; 14) (q24; q11)").gene_a, one("t (8; 14) (q24; q11)").gene_b), ("TRA", "MYC"))

    def test_ambiguous_with_nothing_shared_is_unresolved(self):
        self.assertEqual(one("t(12;22)").status, "unresolved")

    def test_contradicting_bands_are_not_corrected(self):
        # TCF3::PBX1 is q23;p13; a text writing q21 is not silently mapped to it.
        self.assertEqual(one("t(1;19)(q21;p13)").status, "unresolved")

    def test_gene_level_when_the_partner_varies(self):
        r = one("t (X; 18)")
        self.assertEqual((r.gene_a, r.gene_b, r.status), ("SS18", "", "gene_level"))

    def test_nct07012447_names_cbfb_and_pml(self):
        genes = tl.genes_in("favorable cytogenetics (t(8;21), inv(16), t(15,17))")
        self.assertTrue({"CBFB", "PML", "RUNX1"} <= set(genes))


if __name__ == "__main__":
    unittest.main()
