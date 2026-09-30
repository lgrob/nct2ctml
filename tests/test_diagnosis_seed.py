"""
The diagnosis-seed rules from the 2026-09-29 audit
(doc/decisions/2026-09-29-conditions-seed-rules.md), all deterministic and offline.

- A blocked abbreviation seeds nothing: "GCT" resolved to Granular Cell Tumor on a
  germ cell tumour trial, "RAS" to Radiation-Associated Sarcoma on a colorectal one.
- diagnosis_seed_suspect flags a basket resting on the word "oncology" and a
  B-lineage criterion on a trial whose text names only T-lineage disease. Both
  flag; neither removes anything.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.text_rules as text_rules
import utils.reference_validation as rv
from src.trial_map_manager import TrialMapManager as M

B_ALL = text_rules.B_ALL
T_ALL = text_rules.T_ALL


def _nct(conditions, criteria, title=""):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT0TEST", "briefTitle": title},
            "conditionsModule": {"conditions": list(conditions)},
            "eligibilityModule": {"eligibilityCriteria": criteria},
        }
    }


def _tree(*diagnoses):
    return {
        "nct_id": "NCT0TEST",
        "treatment_list": {
            "step": [{"match": [{"clinical": {"oncotree_primary_diagnosis": list(diagnoses)}}]}]
        },
    }


class TestBlockedAbbreviations(unittest.TestCase):
    def setUp(self):
        rv._abbrev_exclusions.cache_clear()
        self.addCleanup(rv._abbrev_exclusions.cache_clear)

    def test_the_shipped_list_blocks_the_two_measured_collisions(self):
        self.assertEqual(sorted(rv._abbrev_exclusions()), ["GCT", "RAS"])

    def test_gct_seeds_nothing_on_a_germ_cell_tumour_trial(self):
        # NCT07188441 published Granular Cell Tumor beside Germ Cell Tumor, Brain.
        got = rv.diagnoses_from_conditions(
            ["GCT", "Germ Cell Tumor", "Central Malignant Germ Cell Tumor"], "NCT07188441"
        )
        self.assertNotIn("Granular Cell Tumor", got)

    def test_ras_seeds_nothing_on_a_colorectal_trial(self):
        got = rv.diagnoses_from_conditions(["Colorectal Neoplasms", "RAS", "BRAF"], "NCT07257653")
        self.assertNotIn("Radiation-Associated Sarcoma", got)

    def test_other_abbreviations_still_resolve(self):
        # The 40 abbreviation seeds in the corpus are otherwise correct; only the
        # measured collisions are blocked (doc/decisions/2026-09-29-conditions-seed-rules.md).
        self.assertEqual(
            rv.diagnoses_from_conditions(["DIPG"]), ["Diffuse Midline Glioma, H3 K27-Altered"]
        )
        self.assertEqual(
            rv.diagnoses_from_conditions(["AML", "MDS"]),
            ["Acute Myeloid Leukemia", "Myelodysplastic Syndromes"],
        )

    def test_a_missing_list_blocks_nothing(self):
        with mock.patch("config.DIAGNOSIS_ABBREV_EXCLUSION_FILE_PATH", "ref/does_not_exist.tsv"):
            rv._abbrev_exclusions.cache_clear()
            self.assertEqual(rv._abbrev_exclusions(), frozenset())
            self.assertEqual(rv.diagnoses_from_conditions(["GCT"]), ["Granular Cell Tumor"])


class TestBasketOnASpecialtyWord(unittest.TestCase):
    def test_oncology_with_a_named_diagnosis_is_flagged(self):
        # NCT04217512: conditions ['Oncology'], text "Patients with head and neck cancer",
        # published _SOLID_ + _LIQUID_ + Head and Neck Carcinoma, Other (879 codes).
        reason = text_rules.diagnosis_seed_suspect(
            ["_SOLID_", "_LIQUID_", "Head and Neck Carcinoma, Other"],
            ["Oncology"],
            "Inclusion Criteria:\n\n* Patients with head and neck cancer",
            ["Oncology"],
        )
        self.assertIn("specialty rather than a population", reason)
        self.assertIn("Oncology", reason)

    def test_a_solid_tumour_basket_is_not_flagged(self):
        # The basket rule is right about these; only the specialty word is distrusted.
        self.assertEqual(
            text_rules.diagnosis_seed_suspect(
                ["_SOLID_", "Neuroblastoma"],
                ["Pediatric Solid Tumor", "Neuroblastoma"],
                "Patients with a relapsed solid tumour.",
                ["Pediatric Solid Tumor"],
            ),
            "",
        )

    def test_cancer_as_the_broad_word_is_not_flagged(self):
        # Measured and not adopted: 10 of the 17 "cancer" trials are category headers.
        self.assertEqual(
            text_rules.diagnosis_seed_suspect(
                ["_SOLID_", "_LIQUID_", "Neuroblastoma"],
                ["Pediatric Cancer", "Neuroblastoma"],
                "Any paediatric malignancy.",
                ["Pediatric Cancer"],
            ),
            "",
        )

    def test_oncology_beside_a_real_broad_term_is_not_flagged(self):
        self.assertEqual(
            text_rules.diagnosis_seed_suspect(
                ["_SOLID_", "Neuroblastoma"],
                ["Oncology", "Solid Tumor"],
                "Any solid tumour.",
                ["Oncology", "Solid Tumor"],
            ),
            "",
        )

    def test_no_wildcard_means_no_flag(self):
        self.assertEqual(
            text_rules.diagnosis_seed_suspect(
                ["Neuroblastoma"], ["Oncology"], "Neuroblastoma patients.", ["Oncology"]
            ),
            "",
        )


class TestLineageMismatch(unittest.TestCase):
    TEXT = "Relapsed or refractory T-ALL/LBL, CD5 positive."

    def test_b_lineage_on_a_t_lineage_trial_is_flagged(self):
        reason = text_rules.diagnosis_seed_suspect(
            [B_ALL, T_ALL], ["Acute Lymphoblastic Leukemia"], self.TEXT, []
        )
        self.assertIn(B_ALL, reason)
        self.assertIn("T-lineage", reason)

    def test_a_trial_naming_both_lineages_is_not_flagged(self):
        self.assertEqual(
            text_rules.diagnosis_seed_suspect(
                [B_ALL, T_ALL],
                ["Acute Lymphoblastic Leukemia"],
                "Relapsed B-ALL or T-ALL after CD19 therapy.",
                [],
            ),
            "",
        )

    def test_a_b_lineage_trial_is_not_flagged(self):
        self.assertEqual(
            text_rules.diagnosis_seed_suspect(
                [B_ALL], ["Acute Lymphoblastic Leukemia"], "Relapsed B-cell ALL.", []
            ),
            "",
        )

    def test_an_excluded_b_lineage_entry_is_not_a_requirement(self):
        self.assertEqual(
            text_rules.diagnosis_seed_suspect([f"!{B_ALL}", T_ALL], [], self.TEXT, []), ""
        )


class TestTheMapperFlagsAndRoutes(unittest.TestCase):
    def test_the_flag_is_written_and_routes_to_review(self):
        ctml = _tree(B_ALL, T_ALL)
        M._flag_diagnosis_seed(
            ctml,
            _nct(["Acute Lymphoblastic Leukemia"], "Relapsed or refractory T-ALL/LBL."),
            "nct",
            "NCT0TEST",
        )
        self.assertIn("T-lineage", ctml["diagnosis_seed_suspect"])
        self.assertNotEqual(M._destination_for(ctml, "cache/ctml", "NCT0TEST"), "cache/ctml")

    def test_nothing_is_removed_from_the_match_tree(self):
        ctml = _tree(B_ALL, T_ALL)
        before = text_rules.collect(ctml)["diagnoses"]
        M._flag_diagnosis_seed(
            ctml, _nct(["Acute Lymphoblastic Leukemia"], "T-ALL only."), "nct", "NCT0TEST"
        )
        self.assertEqual(text_rules.collect(ctml)["diagnoses"], before)

    def test_a_clean_trial_is_not_flagged(self):
        ctml = _tree("Neuroblastoma")
        M._flag_diagnosis_seed(ctml, _nct(["Neuroblastoma"], "Neuroblastoma."), "nct", "NCT0TEST")
        self.assertNotIn("diagnosis_seed_suspect", ctml)

    def test_a_broken_record_does_not_lose_the_trial(self):
        ctml = _tree(B_ALL)
        M._flag_diagnosis_seed(ctml, {"protocolSection": None}, "nct", "NCT0TEST")
        self.assertNotIn("diagnosis_seed_suspect", ctml)


if __name__ == "__main__":
    unittest.main()
