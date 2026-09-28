"""utils/review_helper.py: the checks accept() applies, its log, and the evidence search."""

import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.review_helper as rh

logger.remove()

CTML = """nct_id: NCT0TEST
curated_on: ''
treatment_list:
  step:
  - match:
    - and:
      - clinical:
          oncotree_primary_diagnosis: Neuroblastoma
      - genomic:
          hugo_symbol: ALK
          variant_category: Mutation
          protein_change: {change}
{extra}"""


class _Layers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {
            k: getattr(rh, k) for k in ("MAPPED_DIR", "REVIEW_DIR", "REVIEWED_DIR", "LOG_FILE")
        }
        rh.MAPPED_DIR, rh.REVIEW_DIR, rh.REVIEWED_DIR = (
            os.path.join(self.tmp, d) for d in ("mapped", "review", "reviewed")
        )
        rh.LOG_FILE = os.path.join(self.tmp, "review_log.tsv")
        for d in (rh.MAPPED_DIR, rh.REVIEW_DIR):
            os.makedirs(d)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(rh, k, v)

    def put(self, text, layer="review"):
        with open(os.path.join(self.tmp, layer, "NCT0TEST.yaml"), "w") as fh:
            fh.write(text)


class TestAccept(_Layers):
    def test_a_flagged_file_is_refused(self):
        self.put(CTML.format(change="p.F1174L", extra="          gene_unsupported: ALK\n"))
        with self.assertRaises(SystemExit) as e:
            rh.accept("NCT0TEST", "lgrob")
        self.assertIn("still flagged: gene_unsupported", str(e.exception))
        self.assertTrue(os.path.exists(os.path.join(rh.REVIEW_DIR, "NCT0TEST.yaml")))

    def test_a_wrong_protein_change_is_refused(self):
        # ALK residue 1174 is Phe; Leu1174 would be the variant, not the reference.
        self.put(CTML.format(change="p.L1174F", extra=""))
        with self.assertRaises(SystemExit) as e:
            rh.accept("NCT0TEST", "lgrob")
        self.assertIn("reference_mismatch", str(e.exception))

    def test_no_diagnosis_is_refused(self):
        self.put(CTML.format(change="p.F1174L", extra="").replace("Neuroblastoma", "[]"))
        with self.assertRaises(SystemExit) as e:
            rh.accept("NCT0TEST", "lgrob")
        self.assertIn("no diagnosis", str(e.exception))

    def test_accept_moves_stamps_and_logs(self):
        self.put(CTML.format(change="p.F1174L", extra=""))
        target = rh.accept("NCT0TEST", "lgrob", note="checked", today="2026-09-26")
        self.assertFalse(os.path.exists(os.path.join(rh.REVIEW_DIR, "NCT0TEST.yaml")))
        text = open(target).read()
        self.assertIn("curated_on: '2026-09-26'", text)
        self.assertIn("protein_change: p.F1174L", text)  # curator's text kept as written
        rows = list(csv.DictReader(open(rh.LOG_FILE), delimiter="\t"))
        self.assertEqual(
            (rows[0]["trial_id"], rows[0]["reviewer"], rows[0]["from_layer"], rows[0]["note"]),
            ("NCT0TEST", "lgrob", "needs_review", "checked"),
        )
        self.assertEqual(len(rows[0]["sha256"]), 64)

    def test_a_trial_already_reviewed_is_refused(self):
        os.makedirs(rh.REVIEWED_DIR)
        self.put("old\n", "reviewed")
        self.put(CTML.format(change="p.F1174L", extra=""), "mapped")
        with self.assertRaises(SystemExit):
            rh.accept("NCT0TEST", "lgrob")


class TestExclude(_Layers):
    def setUp(self):
        super().setUp()
        import utils.oncology_scope as scope

        self.scope = scope
        self.saved_overrides = scope.OVERRIDES
        scope.OVERRIDES = os.path.join(self.tmp, "scope_overrides.tsv")
        with open(scope.OVERRIDES, "w") as fh:
            fh.write("# comment\ntrial_id\tdecision\treason\n")

    def tearDown(self):
        self.scope.OVERRIDES = self.saved_overrides
        super().tearDown()

    def test_exclude_writes_a_skip_row_and_logs(self):
        self.put(CTML.format(change="p.F1174L", extra=""), "mapped")
        self.assertEqual(
            rh.exclude("NCT0TEST", "lgrob", "adult-only trial", today="2026-09-26"), ["mapped"]
        )
        o = self.scope.load_overrides(self.scope.OVERRIDES)
        self.assertEqual(o["NCT0TEST"], ("skip", "adult-only trial (lgrob, 2026-09-26)"))
        rows = list(csv.DictReader(open(rh.LOG_FILE), delimiter="\t"))
        self.assertEqual((rows[0]["flags_resolved"], rows[0]["from_layer"]), ("excluded", "mapped"))
        with self.assertRaises(SystemExit):
            rh.exclude("NCT0TEST", "lgrob", "again")

    def test_a_reason_is_required(self):
        with self.assertRaises(SystemExit):
            rh.exclude("NCT0TEST", "lgrob", " ")


class TestEvidence(unittest.TestCase):
    def test_british_spelling_and_hyphens(self):
        hits = rh.find_mentions("relapsed B-lymphoblastic leukaemia", ["B-Lymphoblastic Leukemia"])
        self.assertEqual(len(hits), 1)

    def test_short_symbols_are_case_sensitive_whole_words(self):
        self.assertEqual(rh.find_mentions("patients are eligible", ["AR"]), [])
        self.assertEqual(len(rh.find_mentions("AR-positive", ["AR"])), 1)

    def test_near_miss_spelling(self):
        # 2023-504694-20-00 writes KMT2A as "KTM2A".
        self.assertTrue(rh.near_misses([("inclusion", "including KTM2A/AF4")], "KMT2A"))
        self.assertFalse(rh.near_misses([("inclusion", "including KMT2B")], "KMT2A2"))
        self.assertFalse(rh.near_misses([("inclusion", "MET")], "MEK"))  # under 4 characters

    def test_ambiguous_aliases_never_count_as_support(self):
        ref = rh.Reference()
        self.assertNotIn("ALL", ref.gene_terms("BCR"))
        self.assertIn("ALL", ref.weak_gene_terms("BCR"))


class TestDiagnosesOnlyInExclusions(unittest.TestCase):
    """2023-504999-25-00 (CHIP-AML22): APL, MLDS, MDS and JMML were mapped as diagnoses."""

    INC = "1. Newly diagnosed AML. The origin of AML must be de novo."
    EXC = (
        "2. Myelodysplastic syndrome (MDS). 3. Juvenile Myelomonocytic Leukemia (JMML). "
        "15. Acute promyelocytic leukemia (APL)."
    )

    def test_exclusion_only_diagnoses_are_found(self):
        got = rh.diagnoses_only_in_exclusions(
            [
                "Acute Myeloid Leukemia",
                "Juvenile Myelomonocytic Leukemia",
                "Myelodysplastic Syndromes",
            ],
            self.INC,
            self.EXC,
            ["Acute Myeloid Leukemia"],
        )
        self.assertIn("Juvenile Myelomonocytic Leukemia", got)
        self.assertNotIn("Acute Myeloid Leukemia", got)

    def test_named_in_inclusion_or_title_is_not_reported(self):
        self.assertEqual(
            rh.diagnoses_only_in_exclusions(
                ["Juvenile Myelomonocytic Leukemia"],
                "",
                self.EXC,
                ["A study in juvenile myelomonocytic leukaemia"],
            ),
            [],
        )

    def test_excluded_and_unnamed_diagnoses_are_ignored(self):
        self.assertEqual(
            rh.diagnoses_only_in_exclusions(
                ["!Juvenile Myelomonocytic Leukemia", "Osteosarcoma", "_LIQUID_"],
                self.INC,
                self.EXC,
            ),
            [],
        )

    def test_the_mapper_flags_and_routes_to_review(self):
        from src.trial_map_manager import TrialMapManager as M

        ctml = {
            "treatment_list": {
                "step": [
                    {
                        "match": [
                            {
                                "or": [
                                    {
                                        "clinical": {
                                            "oncotree_primary_diagnosis": "Acute Myeloid Leukemia"
                                        }
                                    },
                                    {
                                        "clinical": {
                                            "oncotree_primary_diagnosis": "Juvenile Myelomonocytic Leukemia"
                                        }
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        record = {
            "protocolSection": {
                "identificationModule": {"briefTitle": "AML trial"},
                "conditionsModule": {"conditions": ["Acute Myeloid Leukemia"]},
                "eligibilityModule": {
                    "eligibilityCriteria": "Inclusion Criteria:\n"
                    + self.INC
                    + "\nExclusion Criteria:\n"
                    + self.EXC
                },
            }
        }
        M._flag_excluded_diagnoses(ctml, record, "nct", "NCT0TEST")
        self.assertEqual(ctml.get("diagnosis_excluded"), "Juvenile Myelomonocytic Leukemia")
        self.assertNotEqual(M._destination_for(ctml, "cache/ctml", "NCT0TEST"), "cache/ctml")

    def test_accept_takes_quoted_excluded_diagnoses(self):
        ctml = {
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
                                    {
                                        "clinical": {
                                            "oncotree_primary_diagnosis": "!APL with PML-RARA"
                                        }
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        self.assertEqual(
            [p for p in rh.problems(ctml, "") if "OncoTree" in p or "excluded" in p], []
        )
        only_neg = {
            "treatment_list": {
                "step": [
                    {
                        "match": [
                            {
                                "and": [
                                    {
                                        "clinical": {
                                            "oncotree_primary_diagnosis": "!APL with PML-RARA"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        self.assertIn(
            "only excluded diagnoses: add the diagnosis the trial enrols", rh.problems(only_neg, "")
        )

    def test_off_list_flag_with_several_names(self):
        self.assertEqual(rh._as_set("A; B"), {"A", "B"})
        self.assertEqual(rh._as_set(["A"]), {"A"})


class TestContradictions(unittest.TestCase):
    """2023-508129-28-00: BCR::ABL1 required, 'no ABL1 variation' forbidden, T315I put on BCR."""

    FUSION = {
        "genomic": {
            "hugo_symbol": "BCR",
            "variant_category": "Structural Variation",
            "fusion_partner": "ABL1",
        }
    }

    def _tree(self, *leaves):
        return {"treatment_list": {"step": [{"match": [{"and": list(leaves)}]}]}}

    def test_a_forbidden_fusion_partner_is_a_contradiction(self):
        import src.match_criteria_mapper as mcm

        t = self._tree(
            self.FUSION, {"genomic": {"hugo_symbol": "ABL1", "variant_category": "!Any Variation"}}
        )
        self.assertEqual(mcm.find_unsatisfiable_genes(t["treatment_list"]), ["ABL1"])

    def test_excluding_one_variant_of_the_partner_is_fine(self):
        import src.match_criteria_mapper as mcm

        t = self._tree(
            self.FUSION,
            {
                "genomic": {
                    "hugo_symbol": "ABL1",
                    "variant_category": "!Mutation",
                    "protein_change": "p.T315I",
                }
            },
        )
        self.assertEqual(mcm.find_unsatisfiable_genes(t["treatment_list"]), [])

    def test_or_alternatives_are_not_a_contradiction(self):
        # 2023-503322-39-00: EWSR1 fusion, or round cell sarcoma without one.
        import src.match_criteria_mapper as mcm

        t = {
            "and": [
                {
                    "or": [
                        {
                            "genomic": {
                                "hugo_symbol": "EWSR1",
                                "variant_category": "Structural Variation",
                            }
                        },
                        {
                            "and": [
                                {
                                    "genomic": {
                                        "hugo_symbol": "EWSR1",
                                        "variant_category": "!Structural Variation",
                                    }
                                }
                            ]
                        },
                    ]
                }
            ]
        }
        self.assertEqual(mcm.find_unsatisfiable_genes(t), [])

    def test_the_mapper_flags_and_routes_it(self):
        from src.trial_map_manager import TrialMapManager as M

        t = self._tree(
            self.FUSION, {"genomic": {"hugo_symbol": "ABL1", "variant_category": "!Any Variation"}}
        )
        M._flag_contradictions(t, "T")
        self.assertEqual(t.get("genomic_contradiction"), "ABL1")
        self.assertNotEqual(M._destination_for(t, "cache/ctml", "T"), "cache/ctml")

    def test_accept_refuses_a_contradiction_even_without_the_flag(self):
        t = self._tree(
            {"clinical": {"oncotree_primary_diagnosis": "Chronic Myeloid Leukemia, BCR-ABL1+"}},
            self.FUSION,
            {"genomic": {"hugo_symbol": "ABL1", "variant_category": "!Any Variation"}},
        )
        self.assertIn("requires and forbids ABL1 under one AND: matches nobody", rh.problems(t, ""))


class TestFlagUnsupportedGenes(_Layers):
    """2026-09-27: 'ICF' (informed consent form) had supported DNMT3B in published trials."""

    MAPPED = (
        "nct_id: NCT0TEST\ntreatment_list:\n  step:\n  - match:\n    - and:\n"
        "      - clinical:\n          oncotree_primary_diagnosis: Neuroblastoma\n"
        "      - genomic:\n          hugo_symbol: {gene}\n          variant_category: Any Variation\n"
    )

    def _run(self, gene, inc, apply=False, comment=""):
        from unittest import mock

        self.put(comment + self.MAPPED.format(gene=gene), layer="mapped")
        with (
            mock.patch.object(rh, "eligibility_text", lambda t: (inc, "", {})),
            mock.patch("utils.oncology_scope.load_report", lambda *a, **k: {}),
            mock.patch("utils.oncology_scope.load_overrides", lambda *a, **k: {}),
        ):
            return rh.flag_unsupported_genes(apply=apply)

    def test_a_gene_supported_only_by_a_blocked_alias_is_flagged_and_moved(self):
        found = self._run(
            "DNMT3B", "Must sign the Informed Consent Form (ICF). Neuroblastoma.", apply=True
        )
        self.assertEqual(
            [(t, layer, g) for t, layer, g, _ in found], [("NCT0TEST", "mapped", ["DNMT3B"])]
        )
        self.assertFalse(os.path.exists(os.path.join(rh.MAPPED_DIR, "NCT0TEST.yaml")))
        moved = open(os.path.join(rh.REVIEW_DIR, "NCT0TEST.yaml")).read()
        self.assertIn("gene_unsupported: DNMT3B", moved)

    def test_a_named_gene_is_not_flagged(self):
        self.assertEqual(self._run("ALK", "Neuroblastoma with an ALK mutation."), [])

    def test_expression_only_gene_is_flagged(self):
        found = self._run("MS4A1", "CD20-positive disease by flow cytometry.")
        self.assertEqual(found[0][2], ["MS4A1 (expression-only)"])

    def test_the_dry_run_writes_nothing(self):
        self._run("DNMT3B", "sign the ICF")
        self.assertTrue(os.path.exists(os.path.join(rh.MAPPED_DIR, "NCT0TEST.yaml")))

    def test_a_file_with_curator_comments_is_never_rewritten(self):
        found = self._run("DNMT3B", "sign the ICF", apply=True, comment="# curator note\n")
        self.assertEqual(found[0][3], "edited: check by hand")
        self.assertTrue(os.path.exists(os.path.join(rh.MAPPED_DIR, "NCT0TEST.yaml")))


class TestAudit(_Layers):
    def test_the_sample_is_reproducible_and_skips_other_layers(self):
        for t in ("A", "B", "C", "D"):
            open(os.path.join(rh.MAPPED_DIR, f"{t}.yaml"), "w").close()
        open(os.path.join(rh.REVIEW_DIR, "B.yaml"), "w").close()
        s1, pool = rh.audit_sample(2, seed=1)
        self.assertEqual(pool, 3)
        self.assertEqual(s1, rh.audit_sample(2, seed=1)[0])
        self.assertNotIn("B", s1)


if __name__ == "__main__":
    unittest.main()
