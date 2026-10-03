"""
Gene encoding rules and the gene-scope check (doc/runs/2026-10-02-3.4-gene-audit.md):
src.text_rules.fix_gene_encodings and gene_scope_suspect.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import src.text_rules as text_rules
import utils.review.common as common
from src.trial_map_manager import TrialMapManager

logger.remove()


def tree(*nodes):
    return {
        "treatment_list": {
            "step": [
                {
                    "match": [
                        {
                            "and": [
                                {
                                    "clinical": {
                                        "oncotree_primary_diagnosis": "Acute Myeloid Leukemia"
                                    }
                                },
                                *nodes,
                            ]
                        }
                    ]
                }
            ]
        }
    }


def gene(symbol, category, **extra):
    return {"genomic": {"hugo_symbol": symbol, "variant_category": category, **extra}}


def genes(ctml):
    return text_rules.collect(ctml)["genomic"]


class TestItd(unittest.TestCase):
    def test_a_required_itd_also_matches_as_a_mutation(self):
        # NCT06262438: FLT3-ITD required as Structural Variation matched no ITD patient.
        t = tree(gene("FLT3", "Structural Variation"))
        notes = text_rules.fix_gene_encodings(t, "FLT3-ITD+ and wild-type NPM1", "")
        self.assertTrue(notes)
        self.assertEqual(
            sorted(g["variant_category"] for g in genes(t)), ["Mutation", "Structural Variation"]
        )
        self.assertIn(
            {"or": [gene("FLT3", "Structural Variation"), gene("FLT3", "Mutation")]},
            t["treatment_list"]["step"][0]["match"][0]["and"],
        )

    def test_an_itd_exclusion_is_left_alone(self):
        # 2023-504999-25-00: CHIP-AML22's ITD exclusion is for one randomisation;
        # making it bite would lose every FLT3-ITD patient.
        t = tree(gene("FLT3", "!Structural Variation"))
        self.assertEqual(text_rules.fix_gene_encodings(t, "", "Presence of FLT3 ITD"), [])

    def test_a_fusion_is_left_alone(self):
        t = tree(gene("FLT3", "Structural Variation"))
        self.assertEqual(text_rules.fix_gene_encodings(t, "FLT3 rearrangement or FLT3-ITD", ""), [])
        t = tree(gene("FLT3", "Structural Variation", fusion_partner="ETV6"))
        self.assertEqual(text_rules.fix_gene_encodings(t, "FLT3-ITD", ""), [])


class TestExclusionProteinChange(unittest.TestCase):
    def test_the_one_named_change_narrows_the_exclusion(self):
        # NCT04166409: "LGG without a BRAFV600E mutation" as BRAF !Mutation.
        t = tree(gene("BRAF", "!Mutation"))
        text_rules.fix_gene_encodings(
            t,
            "non-NF1 low-grade glioma without a BRAFV600E mutation",
            "Prior BRAF inhibitor therapy",
        )
        self.assertEqual(
            genes(t),
            [{"hugo_symbol": "BRAF", "variant_category": "!Mutation", "protein_change": "p.V600E"}],
        )

    def test_a_residue_is_kept_as_a_residue(self):
        # NCT05099003: "without BRAF V600 or IDH1 mutations".
        t = tree(gene("BRAF", "!Mutation"))
        text_rules.fix_gene_encodings(t, "HGG without BRAF V600 or IDH1 mutations", "")
        self.assertEqual(genes(t)[0]["protein_change"], "p.V600")

    def test_a_plain_mention_keeps_the_whole_gene(self):
        t = tree(gene("BRAF", "!Mutation"))
        self.assertEqual(
            text_rules.fix_gene_encodings(t, "without BRAF V600E", "Any BRAF mutation is excluded"),
            [],
        )

    def test_the_duplicate_the_model_wrote_is_dropped(self):
        t = tree(gene("BRAF", "!Mutation"), gene("BRAF", "!Mutation", protein_change="p.V600E"))
        text_rules.fix_gene_encodings(t, "", "Patients with BRAF V600E mutation")
        self.assertEqual(len(genes(t)), 1)


class TestSubgroupNames(unittest.TestCase):
    def test_a_subgroup_name_is_not_a_gene(self):
        # 2024-517133-40-00 (COGNITO-MB): "SHH-activated MB" as SHH Any Variation.
        t = tree(gene("SHH", "Any Variation"))
        notes = text_rules.fix_gene_encodings(t, "diagnosis of SHH-activated MB", "")
        self.assertTrue(notes)
        self.assertEqual(genes(t), [])
        self.assertEqual(
            t["treatment_list"]["step"][0]["match"][0]["and"],
            [{"clinical": {"oncotree_primary_diagnosis": "Acute Myeloid Leukemia"}}],
        )

    def test_a_named_alteration_keeps_the_gene(self):
        t = tree(gene("SHH", "Any Variation"))
        self.assertEqual(
            text_rules.fix_gene_encodings(t, "SHH-activated MB with an SHH mutation", ""), []
        )

    def test_removing_an_exclusion_does_not_empty_the_trial(self):
        # NCT06193759: "Group A patients with medulloblastoma of the SHH subtype".
        t = tree(gene("SHH", "!Any Variation"))
        record = {
            "protocolSection": {
                "eligibilityModule": {
                    "eligibilityCriteria": "Exclusion Criteria:\n* medulloblastoma of the SHH subtype"
                }
            }
        }
        self.assertEqual(TrialMapManager._fix_gene_encodings(t, record, "nct", "NCT0"), [])
        self.assertIn("gene_encoding_fixed", t)

    def test_the_mapper_routes_a_trial_left_without_genes(self):
        t = tree(gene("SHH", "Any Variation"))
        record = {
            "protocolSection": {
                "eligibilityModule": {
                    "eligibilityCriteria": "Inclusion Criteria:\n* SHH subtype medulloblastoma"
                }
            }
        }
        emptied = TrialMapManager._fix_gene_encodings(t, record, "nct", "NCT0")
        self.assertTrue(emptied)
        self.assertIn("gene_encoding_fixed", t)


class TestGeneScope(unittest.TestCase):
    def scoped(self, inclusion, *nodes):
        return set(text_rules.gene_scope_suspect(tree(*nodes), inclusion))

    def test_a_stratifier_is_not_a_requirement(self):
        # NCT07466316: FOXO1 fusion-negative and fusion-positive RMS both enrol.
        inc = "Inclusion Criteria:\n* FOXO1 fusion negative (FN)\n  * Stage 2/3\n* FOXO1 fusion positive (FP)\n  * Stages 1-3"
        self.assertEqual(self.scoped(inc, gene("FOXO1", "Structural Variation")), {"FOXO1"})

    def test_a_cohort_in_the_sentence(self):
        # NCT06411821.
        inc = "* Identified mutation in MAPK pathway genes, including BRAF and MAP2K1 (for primary cohort; no mutation needed for exploratory cohort)."
        self.assertEqual(self.scoped(inc, gene("BRAF", "Mutation")), {"BRAF"})

    def test_an_only_header(self):
        # NCT05372640.
        inc = "* Dose Escalation Cohort Only: evaluable disease\n* Dose Expansion Cohort Only:\n  * NUTM1 rearranged NUT carcinoma"
        self.assertEqual(self.scoped(inc, gene("NUTM1", "Structural Variation")), {"NUTM1"})

    def test_a_phase_section_without_the_gene(self):
        # NCT04901702.
        inc = (
            "Phase I\n\n* Patients with refractory or recurrent non-CNS solid tumors.\n\n"
            "Phase II\n\n* Ewing sarcoma with EWSR1-FLI1 translocation."
        )
        self.assertEqual(
            self.scoped(inc, gene("EWSR1", "Structural Variation", fusion_partner="FLI1")),
            {"EWSR1"},
        )

    def test_a_route_that_needs_no_alteration(self):
        # 2024-515174-27-00 (DAN-CART).
        inc = (
            "1. B-ALL with one of the following: • First VHR relapse (very high risk genetic features "
            "(KMT2A-AFF1, TP53 alterations)) • NCI HR and MRD >= 0.01% at end of consolidation "
            "• Second or greater bone marrow relapse"
        )
        self.assertEqual(
            self.scoped(inc, gene("KMT2A", "Structural Variation"), gene("TP53", "Any Variation")),
            {"KMT2A", "TP53"},
        )

    def test_a_stand_alone_or(self):
        # NCT03150576: TNBC OR germline BRCA.
        inc = "* ER-negative and HER2-negative breast cancer (TNBC).\n\nOR\n\n* Germline BRCA mutation positive."
        self.assertEqual(self.scoped(inc, gene("BRCA1", "Any Variation")), {"BRCA1"})

    def test_labelled_alternatives(self):
        # NCT07159620.
        inc = (
            "2. Diagnosis:\n\n   ETP-ALL: CD7+, CD1a-, MPO negative.\n\n"
            "   Near-ETP-ALL: CD7+, CD5 >75%.\n\n   T-ALL with myeloid mutations: FLT3, DNMT3A.\n3. Newly diagnosed"
        )
        self.assertEqual(self.scoped(inc, gene("FLT3", "Mutation")), {"FLT3"})

    def test_a_list_of_genes_is_not_scoped(self):
        for inc in (
            "Solid tumor that harbors a ROS1 or NTRK1 gene fusion.",
            "at least one of the following: a. CCNE1 amplification b. FBXW7 deleterious mutations",
            "Phase 1: solid tumor with ALK rearrangement.\nPhase 2: NSCLC with ALK rearrangement.",
            "Ewing sarcoma or CIC-rearranged sarcoma, either bone or soft tissue, with CIC rearrangement",
        ):
            self.assertEqual(
                self.scoped(
                    inc,
                    gene("ROS1", "Structural Variation"),
                    gene("CCNE1", "Copy Number Variation"),
                    gene("ALK", "Structural Variation"),
                ),
                set(),
                inc,
            )

    def test_an_arm_criterion_is_already_scoped(self):
        t = {
            "treatment_list": {
                "step": [{"match": [], "arm": [{"match": [gene("FOXO1", "Structural Variation")]}]}]
            }
        }
        self.assertEqual(text_rules.gene_scope_suspect(t, "FOXO1 negative or FOXO1 positive"), {})

    def test_it_routes_to_review(self):
        self.assertIn("gene_scope_suspect", common.FLAG_KEYS)
        t = tree(gene("FOXO1", "Structural Variation"))
        t["gene_scope_suspect"] = "FOXO1"
        self.assertEqual(TrialMapManager._destination_for(t, "out", "NCT0"), "ctml/needs-review")


if __name__ == "__main__":
    unittest.main()


class TestContradictionsAcrossLevels(unittest.TestCase):
    """match_criteria_mapper.find_unsatisfiable_genes, extended after the gene audit."""

    def test_a_fusion_gene_implies_its_partner(self):
        # 2025-522138-29-00: Ph+ CML as BCR SV with ABL1 !Structural Variation.
        from src.match_criteria_mapper import find_unsatisfiable_genes

        t = tree(gene("BCR", "Structural Variation"), gene("ABL1", "!Structural Variation"))
        self.assertEqual(find_unsatisfiable_genes(t["treatment_list"]), ["ABL1"])

    def test_ph_like_without_bcr_abl1_is_fine(self):
        # ABL1 has many partners: ABL-class Ph-like ALL excluding BCR::ABL1 is real.
        from src.match_criteria_mapper import find_unsatisfiable_genes

        t = tree(gene("ABL1", "Structural Variation"), gene("BCR", "!Structural Variation"))
        self.assertEqual(find_unsatisfiable_genes(t["treatment_list"]), [])

    def test_a_step_exclusion_meets_each_arm(self):
        # NCT05118789 (ARROS-1): "driver other than ROS1" as ROS1 !Any Variation.
        from src.match_criteria_mapper import find_unsatisfiable_genes

        t = {
            "step": [
                {
                    "match": [{"and": [gene("ROS1", "!Any Variation")]}],
                    "arm": [
                        {"match": [{"and": [gene("ROS1", "Structural Variation")]}]},
                        {"arm_code": "x"},
                    ],
                }
            ]
        }
        self.assertEqual(find_unsatisfiable_genes(t), ["ROS1"])


class TestRegistryAgeConflict(unittest.TestCase):
    """utils.age_bounds.registry_conflict (audit 2)."""

    def conflict(self, lo, hi, prose):
        import utils.age_bounds as ab

        return ab.registry_conflict(lo, hi, prose)

    def test_an_adult_trial_capped_at_18(self):
        # NCT07529782: maximumAge "18 Years" against "18 years or older".
        prose = {"minimum": {"value": 18, "unit": "years", "inclusive": True}}
        self.assertTrue(self.conflict(">=18", "<19", prose))

    def test_a_registry_narrower_than_the_text(self):
        prose = {
            "minimum": {"value": 2, "unit": "years", "inclusive": True},
            "maximum": {"value": 21, "unit": "years", "inclusive": True},
        }
        self.assertTrue(self.conflict(">=12", "<22", prose))
        self.assertTrue(self.conflict(">=2", "<19", prose))

    def test_a_registry_wider_than_the_text_is_left_alone(self):
        # NCT06664411: minimumAge 14 against ">= 18" over-matches only.
        prose = {"minimum": {"value": 18, "unit": "years", "inclusive": True}}
        self.assertEqual(self.conflict(">=14", None, prose), "")

    def test_the_inclusive_exclusive_year_is_tolerated(self):
        prose = {"maximum": {"value": 21, "unit": "years", "inclusive": False}}
        self.assertEqual(self.conflict(None, "<22", prose), "")

    def test_an_infant_trial_is_not_a_cap(self):
        # NCT05029531: under 1 year, text from birth.
        prose = {"minimum": {"value": 0, "unit": "days", "inclusive": False}}
        self.assertEqual(self.conflict(None, "<1", prose), "")

    def test_it_routes_to_review(self):
        self.assertIn("age_registry_conflict", common.FLAG_KEYS)


class TestArmNarrowerThanStep(unittest.TestCase):
    """src.text_rules.arm_narrower_than_step (third audit)."""

    @staticmethod
    def trial(step_dx, *arms):
        def dx(names):
            return [{"or": [{"clinical": {"oncotree_primary_diagnosis": n}} for n in names]}]

        return {
            "treatment_list": {
                "step": [
                    {
                        "match": dx(step_dx),
                        "arm": [
                            {"arm_code": f"A{i}", "match": dx(a)}
                            if a is not None
                            else {"arm_code": f"A{i}"}
                            for i, a in enumerate(arms)
                        ],
                    }
                ]
            }
        }

    def test_a_step_diagnosis_no_arm_admits(self):
        # NCT00107289: the only arm requires neuroblastoma.
        t = self.trial(["Neuroblastoma", "Pheochromocytoma"], ["Neuroblastoma"])
        self.assertEqual(list(text_rules.arm_narrower_than_step(t)), ["Pheochromocytoma"])

    def test_a_broader_arm_covers_its_children(self):
        t = self.trial(["Pilocytic Astrocytoma", "Ganglioglioma"], ["Encapsulated Glioma"])
        self.assertEqual(text_rules.arm_narrower_than_step(t), {})

    def test_the_arms_together_cover_the_step(self):
        t = self.trial(["Neuroblastoma", "Wilms' Tumor"], ["Neuroblastoma"], ["Wilms' Tumor"])
        self.assertEqual(text_rules.arm_narrower_than_step(t), {})

    def test_an_arm_without_a_diagnosis_admits_everyone(self):
        t = self.trial(["Neuroblastoma", "Pheochromocytoma"], ["Neuroblastoma"], None)
        self.assertEqual(text_rules.arm_narrower_than_step(t), {})

    def test_a_suspended_arm_admits_nobody(self):
        t = self.trial(
            ["Neuroblastoma", "Pheochromocytoma"], ["Neuroblastoma"], ["Pheochromocytoma"]
        )
        t["treatment_list"]["step"][0]["arm"][1]["arm_suspended"] = "Y"
        self.assertEqual(list(text_rules.arm_narrower_than_step(t)), ["Pheochromocytoma"])

    def test_it_routes_to_review(self):
        self.assertIn("arm_narrower_than_step", common.FLAG_KEYS)
        t = self.trial(["Neuroblastoma", "Pheochromocytoma"], ["Neuroblastoma"])
        TrialMapManager._flag_arm_coverage(t, "NCT0")
        self.assertIn("arm_narrower_than_step", t)
        self.assertEqual(TrialMapManager._destination_for(t, "out", "NCT0"), "ctml/needs-review")
