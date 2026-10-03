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


class TestAudit2FalsePositives(unittest.TestCase):
    """The four floor false positives of doc/runs/2026-10-02-3.4-audit-2.md."""

    def test_a_classification_name_is_not_a_population(self):
        # NCT06130579.
        self.assertEqual(
            floor(
                "diagnosed per the International Consensus Classification of Myeloid Neoplasms and Acute Leukemia"
            ),
            [],
        )

    def test_a_lineage_before_acute_leukemia_is_left_to_the_model(self):
        # NCT06742463.
        self.assertEqual(floor("T-cell acute leukemia/lymphoma"), [])
        self.assertIn("Acute Myeloid Leukemia", floor("relapsed acute leukemia"))

    def test_cns_neuroblastoma_is_not_neuroblastoma(self):
        # NCT07087002.
        self.assertEqual(floor("CNS neuroblastoma, FOXR2-activated"), [])
        self.assertEqual(
            floor("high-risk neuroblastoma"), ["Neuroblastoma", "Ganglioneuroblastoma"]
        )

    def test_classical_hodgkin_does_not_add_the_parent(self):
        # NCT06563245.
        self.assertEqual(floor("classical Hodgkin lymphoma"), [])
        self.assertEqual(floor("relapsed Hodgkin lymphoma"), ["Hodgkin Lymphoma"])


class TestAudit3Groups(unittest.TestCase):
    """Group rows for the populations the third audit found missing."""

    def test_ppgl_is_both(self):
        # NCT07680205.
        self.assertEqual(
            floor("phaeochromocytoma or paraganglioma"), ["Pheochromocytoma", "Paraganglioma"]
        )

    def test_germ_cell_tumour_means_every_extracranial_site(self):
        # 2024-520054-38-00 was published testis only.
        found = floor("de novo or recurrent germ cell tumour")
        self.assertIn("Ovarian Germ Cell Tumor", found)
        self.assertIn("Extra Gonadal Germ Cell Tumor", found)
        self.assertNotIn("Germ Cell Tumor, Brain", found)
        self.assertEqual(floor("CNS germ cell tumours"), ["Germ Cell Tumor, Brain"])
        self.assertEqual(floor("non-seminomatous germ cell tumor"), [])

    def test_b_cell_malignancies_include_b_all(self):
        # NCT06092047.
        self.assertEqual(
            floor("CD19-positive B-cell hematolymphatic malignancies"),
            [B_ALL, "Mature B-Cell Neoplasms"],
        )
        self.assertEqual(floor("mature B-cell malignancies"), ["Mature B-Cell Neoplasms"])

    def test_myelofibrosis_and_head_and_neck(self):
        self.assertIn("Polycythaemia Vera Myelofibrosis", floor("myelofibrosis"))
        self.assertEqual(floor("primary myelofibrosis"), [])
        self.assertIn("Nasopharyngeal Carcinoma", floor("history of head and neck cancer"))

    def test_solid_and_hematologic_malignancies(self):
        self.assertEqual(floor("solid and hematologic malignancies"), ["_SOLID_", "_LIQUID_"])

    def test_myeloid_acute_leukemia_is_left_to_the_model(self):
        # NCT05503134 (KARMA).
        self.assertEqual(floor("Relapsed/Refractory Myeloid Acute Leukemia"), [])


class TestAudit3SmallRows(unittest.TestCase):
    def test_ball_is_b_all_in_capitals_only(self):
        # 2023-508357-58-00.
        self.assertEqual(floor("CD123+ BALL"), [B_ALL])
        self.assertEqual(floor("play with a ball"), [])

    def test_aggressive_b_nhl_lists_the_aggressive_types(self):
        # NCT05533775: published Burkitt, DLBCL and PMBCL only.
        found = floor("aggressive mature B-cell non-Hodgkin lymphoma (B-NHL)")
        self.assertIn("High-Grade B-Cell Lymphoma, NOS", found)
        self.assertNotIn("Follicular Lymphoma", found)
        # NCT04055220: an HIV clause, not the population.
        self.assertEqual(
            floor("No history of AIDS-defining cancers (e.g. aggressive B-cell lymphoma)"), []
        )

    def test_solid_tumor_or_lymphoma(self):
        # NCT04084067: published _SOLID_ only.
        found = floor("primary or relapsed solid tumor or lymphoma")
        self.assertIn("_SOLID_", found)
        self.assertIn("Hodgkin Lymphoma", found)


class TestFloorReadsTitleAndConditions(unittest.TestCase):
    def _run(self, conditions, text, title):
        with (
            mock.patch.object(config, "DIAGNOSIS_TEXT_FLOOR", True),
            mock.patch.object(
                diagnosis, "map_eligibility_criteria_to_oncotree_term", return_value=[]
            ),
        ):
            return diagnosis.seed_and_map_diagnosis("NCT0", conditions, text, title=title)[0]

    def test_the_title_names_the_population(self):
        # NCT07573111: "acute leukemia" only in the title and conditions.
        seeded = self._run(
            [],
            "Inclusion Criteria: HSCT for high-risk malignant disease",
            "High-Risk Acute Leukemias",
        )
        self.assertIn(T_ALL, seeded)

    def test_a_title_basket_only_when_nothing_specific_is_found(self):
        # 2023-510424-68-00 against NCT05658640 (an umbrella title over a subprotocol).
        self.assertIn(
            "_LIQUID_",
            self._run([], "Inclusion Criteria: malignancy", "Solid Tumours and Blood Cancer"),
        )
        seeded = self._run(
            [],
            "Inclusion Criteria: relapsed ALL",
            "Relapsed or Refractory Hematological Malignancies, Subprotocol D",
        )
        self.assertNotIn("_LIQUID_", seeded)

    def test_a_conditions_header_is_not_a_basket(self):
        seeded = self._run(["Pediatric Solid Tumor", "Osteosarcoma"], "", "")
        self.assertNotIn("_SOLID_", seeded)

    def test_the_title_never_removes_what_the_text_gave(self):
        # NCT04099966: a "B-cell" title must not veto the T-lineage the text admits.
        seeded = self._run([], "Inclusion Criteria: ALL", "B-cell depleted transplant")
        self.assertIn(T_ALL, seeded)


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
