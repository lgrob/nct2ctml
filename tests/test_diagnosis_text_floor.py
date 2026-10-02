"""
The diagnosis text floor: populations the eligibility text names in words the
model does not map (ref/diagnosis_groups.tsv), added to its answer. Built for
the largest cause in doc/runs/2026-10-02-3.4-audit.md.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import src.mapping.diagnosis as diagnosis
import utils.reference_validation as rv

logger.remove()

B_ALL = "B-Lymphoblastic Leukemia/Lymphoma"
T_ALL = "T-Lymphoblastic Leukemia/Lymphoma"


def floor(text):
    return rv.diagnoses_from_text(text, "NCT0")


class TestTable(unittest.TestCase):
    def test_every_row_loads_with_oncotree_targets(self):
        groups = rv._diagnosis_groups()
        self.assertGreater(len(groups), 100)
        for term, _, _, targets in groups:
            self.assertTrue(targets, term)
            for t in targets:
                self.assertEqual(rv.canonical_diagnosis(t), t, (term, t))

    def test_an_alias_row_takes_the_targets_of_the_row_it_names(self):
        by_term = {g[0]: g[3] for g in rv._diagnosis_groups()}
        self.assertEqual(by_term["STS"], by_term["soft tissue sarcoma"])
        self.assertEqual(by_term["DIPG"], by_term["diffuse intrinsic pontine glioma"])


class TestMatching(unittest.TestCase):
    def test_a_group_word_floors_the_whole_group(self):
        # NCT06474676: published as Liposarcoma only.
        found = floor("locally advanced or metastatic soft tissue or bone sarcoma")
        for t in ("Rhabdomyosarcoma", "Synovial Sarcoma", "Osteosarcoma", "Ewing Sarcoma"):
            self.assertIn(t, found)

    def test_pre_2021_names_reach_their_successors(self):
        # NCT05956821, NCT03911388.
        found = floor("anaplastic astrocytoma (AA), oligodendroglioma, or DIPG")
        self.assertIn("Astrocytoma, IDH-Mutant, Grade 3", found)
        self.assertIn("Oligodendroglioma, IDH-mutant, and 1p/19q-Codeleted", found)
        self.assertIn("Diffuse Midline Glioma, H3 K27-Altered", found)

    def test_low_grade_glioma_includes_pilocytic_astrocytoma(self):
        # NCT06381570: published without the commonest BRAF-altered pLGG.
        self.assertIn("Pilocytic Astrocytoma", floor("Progressive/Recurrent LGG (non-NF1)"))

    def test_the_longest_term_wins(self):
        found = floor("relapsed non-Hodgkin lymphoma")
        self.assertNotIn("Hodgkin Lymphoma", found)
        self.assertIn("Mature B-Cell Neoplasms", found)

    def test_a_qualified_sarcoma_is_not_the_sarcoma_group(self):
        self.assertEqual(floor("Kaposi sarcoma"), [])
        self.assertEqual(floor("Ewing sarcoma"), ["Ewing Sarcoma", "Ewing Sarcoma of Soft Tissue"])

    def test_a_lineage_before_all_blocks_the_other_lineage(self):
        for text in ("CD19+ B-ALL", "B-cell acute lymphoblastic leukemia", "Ph+ ALL", "T-ALL"):
            self.assertEqual(floor(text), [], text)

    def test_unqualified_all_means_either_lineage(self):
        # 2025-522052-13-00 (FORUM2): published as B-ALL only.
        self.assertEqual(floor("transplant indication for ALL"), [B_ALL, T_ALL])

    def test_an_abbreviation_is_matched_as_written(self):
        self.assertEqual(floor("All patients must consent."), [])

    def test_an_enumerated_basket_is_not_a_basket(self):
        self.assertNotIn("_SOLID_", floor("one of the following solid tumors: neuroblastoma"))
        self.assertIn("_SOLID_", floor("Has a metastatic or locally advanced solid tumor"))


class TestTwoSidedGuards(unittest.TestCase):
    """A guard with "§" sees the text on both sides of the term (TODO 2)."""

    def test_an_organisation_is_not_a_population(self):
        self.assertEqual(floor("sites in the Blood Cancer United territory"), [])
        self.assertEqual(floor("lay title: a blood cancer trial"), ["_LIQUID_"])

    def test_an_enumeration_after_the_term_is_not_a_basket(self):
        self.assertEqual(
            floor("solid tumors of the following types: neuroblastoma"),
            ["Neuroblastoma", "Ganglioneuroblastoma"],
        )

    def test_a_lineage_after_the_term_blocks_it(self):
        self.assertEqual(floor("acute lymphoblastic leukemia (B-ALL)"), [])
        self.assertEqual(floor("NHL of B-cell origin"), [])

    def test_a_grade_i_glioma_is_left_to_the_model(self):
        # NCT07110246: "LGG WHO Grade I" must not floor the grade 2 entities.
        self.assertEqual(floor("confirmed LGG World Health Organization (WHO) Grade I"), [])
        self.assertIn("Pilocytic Astrocytoma", floor("LGG WHO grade I or II"))

    def test_naming_and_expertise_are_not_populations(self):
        self.assertEqual(floor("International Classification of Rhabdomyosarcoma"), [])
        self.assertEqual(floor("pathologists with expertise in bone sarcomas"), [])


class TestFloorInTheMapper(unittest.TestCase):
    TEXT = (
        "Title: A sarcoma trial\nInclusion Criteria: relapsed or refractory sarcoma\n"
        "Exclusion Criteria: Ewing sarcoma"
    )

    def _run(self, on):
        with (
            mock.patch.object(config, "DIAGNOSIS_TEXT_FLOOR", on),
            mock.patch.object(
                diagnosis,
                "map_eligibility_criteria_to_oncotree_term",
                return_value=["Osteosarcoma"],
            ),
        ):
            return diagnosis.seed_and_map_diagnosis("NCT0", [], self.TEXT)

    def test_off_changes_nothing(self):
        self.assertEqual(self._run(False), ([], ["Osteosarcoma"]))

    def test_on_adds_to_the_seed_and_never_removes(self):
        seeded, from_eligibility = self._run(True)
        self.assertEqual(from_eligibility, ["Osteosarcoma"])
        self.assertIn("Synovial Sarcoma", seeded)
        self.assertNotIn("Osteosarcoma", seeded)

    def test_the_exclusion_criteria_are_not_read(self):
        self.assertEqual(
            diagnosis.population_text(self.TEXT),
            "Title: A sarcoma trial\nInclusion Criteria: relapsed or refractory sarcoma\n",
        )


if __name__ == "__main__":
    unittest.main()
