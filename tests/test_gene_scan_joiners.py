"""
The gene scan finds both genes of a fusion and every gene of an unspaced list.

Every string here is copied from the eligibility text of one of the 55
reviewed trials (trial id beside it). Before this change the scan split only
on whitespace, so on those trials it missed a curated gene in 12 of them;
now in 2, and both of those name the gene only as a karyotype or a gene
family (see test_what_the_scan_still_cannot_see).
"""
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import utils.reference_validation as rv
from src.trial_criteria_to_genes import TrialCriteriaToGenes

logger.remove()


class TestGeneScanJoiners(unittest.TestCase):
    def setUp(self):
        self.mapping = rv.gene_synonym_mapping()

    def scan(self, text):
        return sorted(TrialCriteriaToGenes(text, self.mapping).extract_official_gene_symbols())

    def test_double_colon_fusions(self):
        # NCT06177067
        self.assertEqual(
            self.scan("NPM1 mutation or fusion, PICALM::MLLT10, DEK::NUP214, UBTF-TD, "
                      "KAT6A rearrangement (KAT6Ar), or SET::NUP214"),
            ["DEK", "KAT6A", "MLLT10", "NPM1", "NUP214", "PICALM", "UBTF"])

    def test_hyphen_fusions(self):
        # NCT05745714, NCT03643276, NCT05180825
        self.assertEqual(
            self.scan("alterations leading to CRLF2 overexpression "
                      "(P2RY8-CRLF2, IGH-CRLF2, and CRLF2 F232C)"),
            ["CRLF2", "P2RY8"])
        self.assertEqual(self.scan("Ph+ (BCR-ABL1 or t(9;22)-positive) ALL"),
                         ["ABL1", "BCR"])
        self.assertIn("BRAF", self.scan(
            "Determination of a negative BRAFv600 mutation by immunohistochemistry "
            "or KIAA1549-BRAF fusion"))
        # A partner that is not a gene symbol (USP9X is off the reference) is
        # simply not found; the gene next to it still is.
        self.assertIn("DDX3X", self.scan(
            "USP9X truncating mutation or USP9X-DDX3X fusion; STAT5B and DNM2 mutations;"))

    def test_slash_shorthand_for_sibling_genes(self):
        # NCT07012447
        self.assertEqual(
            self.scan("mutations (including FLT3, DNMT3A, STAG2, IDH1/2, RUNX1, EZH2, WT1, "
                      "ASXL1/2, SF3B1, TET2, BCOR, BCORL1, and"),
            ["ASXL1", "ASXL2", "BCOR", "BCORL1", "DNMT3A", "EZH2", "FLT3", "IDH1", "IDH2",
             "RUNX1", "SF3B1", "STAG2", "TET2", "WT1"])
        # NCT05745714, NCT07215910
        self.assertEqual(self.scan("EPOR fusions; JAK1/2/3: Recurrent or novel missense"),
                         ["EPOR", "JAK1", "JAK2", "JAK3"])
        self.assertEqual(self.scan("(CDKN2A/B and1p/19q co-deletion"), ["CDKN2A", "CDKN2B"])

    def test_shorthand_expands_only_to_a_current_symbol(self):
        # NCT03838042. MYC/N is MYC and MYCN; the other reading, MYN, is an
        # alias of PALLD and must not appear.
        found = self.scan("SNV load, MYC/N amplification")
        self.assertEqual(found, ["MYC", "MYCN"])

    def test_short_aliases_do_not_start_resolving_inside_a_token(self):
        # CAR -> PRKAR1A, H3 -> histone genes, ALL -> BCR, B7 -> CD80 would all
        # be collisions. NCT04897321, 2023-509392-17-00, 2025-520982-39-00.
        self.assertEqual(self.scan("in the 7 days prior to B7-H3-CAR T-cell infusion"), [])
        self.assertEqual(self.scan("Chimeric Antigen Receptor T-cell therapy (CAR-T), "
                                   "adoptive T-cell therapy"), [])
        self.assertNotIn("BCR", self.scan("newly diagnosed Ph+ or ABL-class Ph-like B-ALL."))

    def test_markdown_escapes(self):
        # NCT07297979: ERG was lost to the escaped bracket.
        self.assertEqual(self.scan("family gene, eg, FLI1, ETS-related gene \\[ERG\\]) via"),
                         ["ERG", "FLI1"])
        # NCT05183035: unescaping must not let the 2-letter alias SF become HGF.
        self.assertEqual(self.scan("(shortening fraction \\[SF\\] \\< 25% or "
                                   "ejection fraction \\[EF\\] \\< 40%)"), [])

    def test_proto_oncogene_c_prefix(self):
        # NCT05658640
        self.assertIn("CBL", self.scan(
            "PTPN11, MAP2K1, MP2K1 hotspot mutations, cCBL; NF1 del, as detected"))

    def test_what_the_scan_still_cannot_see(self):
        # NCT07012447 curates CBFB and PML from karyotypes; the scan does not
        # read them (utils/translocations.py supplies them as evidence only).
        self.assertEqual(self.scan("such as t(8;21), t(15;17), inv(16)/t(16;16) leukemia"), [])

    def test_nf1_and_nf2_written_with_a_hyphen(self):
        # Roadmap 6.9. "NF-1"/"NF-2" were in neither synonym table, so the
        # scan missed them and the unsupported-gene check flagged a correct
        # NF1 criterion (3.1 dry run: NCT04775485, NCT07110246; the key for
        # NCT04775485 curates NF1 from "NF-1"). Added to the addendum on
        # evidence: all 15 mentions in the cached corpus (11 trials) refer to
        # neurofibromatosis, and NCBI Gene resolves "NF-1" only to NF1 and
        # "NF-2" only to NF2, not to the nuclear factor I genes (NFIA/B/C/X).
        self.assertEqual(self.scan("neurofibromatosis type 1 (NF-1) via genetic testing"), ["NF1"])
        self.assertEqual(self.scan("clinical criteria for the diagnosis of NF-2"), ["NF2"])


if __name__ == '__main__':
    unittest.main()
