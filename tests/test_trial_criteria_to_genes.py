import unittest
from typing import Dict, List

import utils.reference_validation as rv
from src.trial_criteria_to_genes import TrialCriteriaToGenes

# run tests:
# python -m unittest tests.test_trial_criteria_to_genes.TestTrialCriteriaToGenes.test_extract_official_gene_symbols_kras_family_3 -v

class TestTrialCriteriaToGenes(unittest.TestCase):
    def setUp(self):
        self.mapping = self.load_gene_synonym_mapping()

    def load_gene_synonym_mapping(self) -> Dict[str, List[str]]:
        """The same mapping production uses; no second copy of the loader."""
        return rv.gene_synonym_mapping()

    def test_extract_official_gene_symbols_kras_family_1(self):
        criteria = "Patients with KRAS/NRAS/HRAS mutations are eligible."
        tcg = TrialCriteriaToGenes(
            trial_criteria=criteria,
            synonym_to_symbol=self.mapping,
        )
        symbols = tcg.extract_official_gene_symbols()
        print(f"\nsymbols: {symbols}")
        self.assertCountEqual(symbols, ["KRAS", "NRAS","HRAS"])

    def test_extract_official_gene_symbols_kras_family_2(self):
        criteria = "Subject must have documented KRAS p.G12C and EGFR, BRCA1 mutation"
        tcg = TrialCriteriaToGenes(
            trial_criteria=criteria,
            synonym_to_symbol=self.mapping,
        )
        symbols = tcg.extract_official_gene_symbols()
        print(f"\nsymbols: {symbols}")
        self.assertCountEqual(symbols, ["KRAS", "EGFR", "BRCA1"])

    def test_extract_official_gene_symbols_kras_family_3(self):
        criteria = (
        "Inclusion:\n\n"
        "* Subject must have a histologically or cytologically confirmed metastatic or locally advanced "
        "solid tumor which is progressing.\n"
        "* Subject must have documented KRAS p.G12C mutation identified within the last 5 years by a "
        "local test on tumor tissue or blood.\n"
        "* Subject must have measurable disease per RECIST v1.1.\n"
        "* Subject must have Eastern Cooperative Oncology Group (ECOG) performance status of 0 or 1.\n"
        "* Subject must have adequate organ and marrow function within the screening period.\n\n"
        "Exclusion:\n\n"
        "* Subject has any prior treatment with other treatments without adequate washout periods as "
        "defined in the protocol.\n"
        "* Subject has uncontrolled intercurrent illness, including but not limited to, ongoing or "
        "active infection, uncontrolled or significant cardiovascular disease, serious chronic "
        "gastrointestinal conditions associated with diarrhea, or psychiatric illness/social situations "
        "that would limit compliance with study requirements, substantially increase risk of incurring "
        "AEs, or compromise the ability of the subject to give written informed consent.\n"
        "* Subject has unresolved treatment-related toxicities from previous anticancer therapy of "
        "NCI CTCAE Grade ≥2 (with exception of vitiligo or alopecia).\n"
        "* Subject has active gastrointestinal disease or other that could interfere significantly with "
        "the absorption, distribution, metabolism, or excretion of oral therapy.\n"
        "* Concurrent participation in any clinical research study involving treatment with any "
        "investigational drug, radiotherapy, or surgery, except for the nontreatment phases of these "
        "studies (e.g., follow-up phase).\n\n"
        "Other protocol inclusion/exclusion criteria may apply")
        tcg = TrialCriteriaToGenes(
            trial_criteria=criteria,
            synonym_to_symbol=self.mapping,
        )
        symbols = tcg.extract_official_gene_symbols()
        print(f"\nsymbols: {symbols}")

        expected_symbols = ['KRAS'] 
        print(f"Expected symbols: {expected_symbols}")
        self.assertCountEqual(symbols, expected_symbols)

    def test_extract_official_gene_symbols_kras_family_4(self):
        criteria = ("PHASE 1\n\nKey Inclusion Criteria:\n\n1. "
        "Histologically or cytologically confirmed diagnosis of locally advanced, or metastatic solid tumor (including primary CNS tumors) "
        "(Stage IV, American Joint Committee on Cancer v.7) that harbors an ALK, ROS1, NTRK1, NTRK2, or NTRK3 gene rearrangement by "
        "protocol specified tests.\n2. ECOG PS 0-1.\n3. Age \u226518 (or age \u2265 20 of age as required by local regulation).\n4. "
        "Capability to swallow capsules intact (without chewing, crushing, or opening).\n5. At least 1 measurable target lesion according "
        "to RECIST version 1.1. CNS-only measurable disease as defined by RECIST version 1.1 is allowed.\n6. "
        "Prior cytotoxic chemotherapy is allowed.\n7. Prior immunotherapy is allowed.\n8. Resolution of all acute toxic effects "
        "(excluding alopecia) of any prior anti-cancer therapy to National Cancer Institute Common Terminology Criteria for Adverse Events"
        "(NCI CTCAE) Version 4.03 Grade less than or equal to 1.\n9. Patients with asymptomatic CNS metastases (treated or untreated) "
        "and/or asymptomatic leptomeningeal carcinomatosis are eligible to enroll if they satisfy the protocol specified criteria.\n10. "
        "Baseline laboratory values fulfilling the following requirements:Absolute neutrophils count (ANC) \u22651500/mm3 (1.5 \u00d7 109/L);"
        "Platelets (PLTs) \u2265100,000/mm3 (100 \u00d7 109/L); Hemoglobin \u2265 9.0 g/dL transfusions are allowed; Serum creatinine or "
        "creatinine clearance Within normal limits or \\> 40 mL/min; Total serum bilirubin \\< 1.5 \u00d7 ULN; Liver transaminases"
        "(ASTs/ALTs) \\< 2.5 \u00d7 ULN; \\< 5 \u00d7 ULN if liver metastases are present Alkaline phosphatase (ALP);"
        "\\< 2.5 \u00d7 ULN; \\< 5 \u00d7 ULN if liver and/or bone metastasis are present; Serum calcium, magnesium, and potassium Normal or")       

        tcg = TrialCriteriaToGenes(
            trial_criteria=criteria,
            synonym_to_symbol=self.mapping,
        )
        symbols = tcg.extract_official_gene_symbols()
        print(f"\nsymbols: {symbols}")

        expected_symbols = ['ALK','ROS1','NTRK1','NTRK2','NTRK3'] 
        print(f"Expected symbols: {expected_symbols}")
        self.assertCountEqual(symbols, expected_symbols)

    def test_extract_official_gene_symbols_kras_family_5(self):
        criteria = ("Key Inclusion Criteria:\n\n1. "
        "Documented genetic ROS1 point mutation, fusion, or amplification or NTRK1-3 fusion")

        tcg = TrialCriteriaToGenes(
            trial_criteria=criteria,
            synonym_to_symbol=self.mapping,
        )
        symbols = tcg.extract_official_gene_symbols()
        print(f"\nsymbols: {symbols}")

        expected_symbols = ['ROS1', 'NTRK1','NTRK2','NTRK3'] 
        print(f"Expected symbols: {expected_symbols}")
        self.assertCountEqual(symbols, expected_symbols)

    def test_extract_official_gene_symbols_kras_family_6(self):
        criteria = "Patients with RAS-mutated genes are eligible."
        tcg = TrialCriteriaToGenes(
            trial_criteria=criteria,
            synonym_to_symbol=self.mapping,
        )
        symbols = tcg.extract_official_gene_symbols()
        print(f"\nsymbols: {symbols}")
        self.assertCountEqual(symbols, ["KRAS", "NRAS","HRAS"])

if __name__ == "__main__":
    unittest.main()