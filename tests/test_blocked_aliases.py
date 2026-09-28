"""Short NCBI aliases that mean something else in trial text (2026-09-27)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.reference_validation as rv
from src.trial_criteria_to_genes import TrialCriteriaToGenes

logger.remove()
SYN = rv.gene_synonym_mapping()


def scan(text):
    return set(
        TrialCriteriaToGenes(
            trial_criteria=text, synonym_to_symbol=SYN
        ).extract_official_gene_symbols()
    )


class TestBlockedAliases(unittest.TestCase):
    def test_clinical_abbreviations_are_not_genes(self):
        cases = {
            "Relapse after anti-CD19 CAR T-cell therapy": "PRKAR1A",
            "New York Heart Association Class II or greater": "CD74",
            "sign the Informed Consent Form (ICF)": "DNMT3B",
            "tumour cells in the cerebrospinal fluid (CSF)": "CSF2",
            "aggressive B-cell Non-Hodgkin Lymphoma (NHL)": "RTEL1",
            "inoperable PN due to symptoms": "USB1",
            "shortening fraction (SF) >= 27%": "HGF",
            "mantle cell lymphoma (MCL)": "FH",
            "no myocardial infarction (MI) within 6 months": "MITF",
            "a single FSH measurement is insufficient": "BRD2",
            "HIV1/2 NAT": "BRD2",
            "Randomisation B1 & B2": "MS4A1",
            "within 2 months of IP administration": "SDHB",
            "a. Alopecia (Grade <=2) b. Sensory neuropathy": "ELF2",
            "juvenile myelomonocytic leukemia (JMML)": "PTPN11",
        }
        for text, gene in cases.items():
            self.assertNotIn(gene, scan(text), text)

    def test_the_gene_symbols_themselves_still_resolve(self):
        got = scan("PTPN11, CBL or NRAS mutation in JMML; PRKAR1A; DNMT3B; MITF amplification")
        self.assertTrue({"PTPN11", "PRKAR1A", "DNMT3B", "MITF"} <= got, got)


class TestCd20IsExpression(unittest.TestCase):
    def test_ms4a1_is_expression_only(self):
        from src import trial_config

        self.assertIn("MS4A1", trial_config.expression_only_genes)


if __name__ == "__main__":
    unittest.main()
