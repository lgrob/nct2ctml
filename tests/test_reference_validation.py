import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

from utils.reference_validation import (
    canonical_diagnosis,
    canonical_gene,
    diagnoses_from_conditions,
    filter_diagnoses,
    filter_genomic_criteria,
    strip_condition_qualifiers,
)

logger.remove()  # the filters log every drop; tests assert on return values


def _ref(name):
    return os.path.join(os.path.dirname(__file__), '..', 'ref', name)


def _genomic(symbol, category="Mutation"):
    return {"genomic": {"hugo_symbol": symbol, "variant_category": category}}


class TestCanonicalDiagnosis(unittest.TestCase):
    def test_display_name_passes_through(self):
        self.assertEqual(canonical_diagnosis("Neuroblastoma"), "Neuroblastoma")

    def test_code_is_rewritten_to_the_display_name(self):
        # The model returned "AML" on NCT05183035 where CTML wants the name.
        self.assertEqual(canonical_diagnosis("AML"), "Acute Myeloid Leukemia")

    def test_case_is_forgiven(self):
        self.assertEqual(canonical_diagnosis("acute myeloid leukemia"),
                         "Acute Myeloid Leukemia")

    def test_invented_terms_are_rejected(self):
        # Observed in benchmark output; neither is an Oncotree node.
        self.assertIsNone(canonical_diagnosis("Leukemia"))
        self.assertIsNone(canonical_diagnosis("_GASEOUS_"))

    def test_matchminer_wildcards_are_accepted(self):
        """
        _SOLID_ and _LIQUID_ are not Oncotree names, they are how CTML says
        "any solid tumour" / "any liquid tumour". The pipeline derives them
        from the trial's conditions, so rejecting them here silently stripped
        the diagnosis off every basket trial.
        """
        self.assertEqual(canonical_diagnosis("_SOLID_"), "_SOLID_")
        self.assertEqual(canonical_diagnosis("_LIQUID_"), "_LIQUID_")

    def test_parent_and_child_are_both_valid(self):
        # BLL is the parent of BLLNOS. Preferring one over the other is a
        # curation decision, not a validity one, so both survive.
        self.assertEqual(canonical_diagnosis("B-Lymphoblastic Leukemia/Lymphoma"),
                         "B-Lymphoblastic Leukemia/Lymphoma")
        self.assertEqual(canonical_diagnosis("B-Lymphoblastic Leukemia/Lymphoma, NOS"),
                         "B-Lymphoblastic Leukemia/Lymphoma, NOS")

    def test_empty_input(self):
        self.assertIsNone(canonical_diagnosis(""))
        self.assertIsNone(canonical_diagnosis(None))


class TestCanonicalGene(unittest.TestCase):
    def test_known_symbol_passes_through(self):
        self.assertEqual(canonical_gene("MYCN"), "MYCN")

    def test_case_is_forgiven(self):
        self.assertEqual(canonical_gene("braf"), "BRAF")

    def test_hallucinated_symbols_are_rejected(self):
        # "H3" appeared beside the three real histone genes on NCT05580562;
        # "H3K27" is a modification, "RMS" a tumour abbreviation.
        for symbol in ("H3", "H3K27", "RMS"):
            self.assertIsNone(canonical_gene(symbol), symbol)

    def test_real_histone_genes_survive(self):
        for symbol in ("H3-3A", "H3-3B", "H3C2"):
            self.assertEqual(canonical_gene(symbol), symbol)


class TestRetiredGeneSymbols(unittest.TestCase):
    """
    ref/genes.txt is current HGNC; ref/genes_kispi.txt is the raw list. The
    difference is a set of renames, and those are the only rewrites allowed.
    """

    def test_retired_symbols_are_brought_up_to_date(self):
        for retired, current in (("H3F3A", "H3-3A"), ("H3F3B", "H3-3B"),
                                 ("HIST1H3B", "H3C2"), ("WHSC1", "NSD2"),
                                 ("SEPT9", "SEPTIN9"), ("MKL1", "MRTFA"),
                                 ("CARS", "CARS1"), ("ACPP", "ACP3")):
            self.assertEqual(canonical_gene(retired), current, retired)

    def test_every_legacy_symbol_resolves(self):
        """No symbol Kispi listed should be lost to a rename."""
        genes = {l.strip() for l in open(_ref("genes.txt")) if l.strip()}
        legacy = {l.strip() for l in open(_ref("genes_kispi.txt")) if l.strip()}
        unresolved = [s for s in legacy - genes if canonical_gene(s) is None]
        self.assertEqual(unresolved, [])

    def test_short_aliases_are_not_rewritten(self):
        """
        The guard that matters. The full synonym table maps ALL to BCR, AT to
        BTK, ARF to CDKN2A and H3 to H3C14. In a paediatric pipeline "ALL"
        means acute lymphoblastic leukaemia in nearly every trial, so a rewrite
        would invent a BCR criterion where the model said a disease name. A
        drop is visible in the log; a wrong rewrite is not.
        """
        for alias in ("ALL", "AT", "ARF", "AGO", "H3", "AA", "ABL", "AKT"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_multi_gene_aliases_are_not_rewritten(self):
        # "RAS" -> KRAS,NRAS,HRAS: no single symbol to rewrite to.
        for alias in ("RAS", "KRAS/NRAS/HRAS", "RAS-mutated"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_the_rewrite_set_stays_small(self):
        from utils.reference_validation import _gene_aliases
        self.assertLess(len(_gene_aliases()), 40,
                        "the rewrite set grew; it should only hold renames "
                        "between genes.txt and genes_kispi.txt")


class TestFilterDiagnoses(unittest.TestCase):
    def test_drops_unknown_and_keeps_known(self):
        self.assertEqual(filter_diagnoses(["Leukemia", "Neuroblastoma"]),
                         ["Neuroblastoma"])

    def test_wildcards_survive_filtering(self):
        self.assertEqual(filter_diagnoses(["_SOLID_", "_LIQUID_", "Leukemia"]),
                         ["_SOLID_", "_LIQUID_"])

    def test_deduplicates_after_canonicalisation(self):
        # The code and the name are the same node, so only one survives.
        self.assertEqual(filter_diagnoses(["AML", "Acute Myeloid Leukemia"]),
                         ["Acute Myeloid Leukemia"])

    def test_order_is_stable(self):
        self.assertEqual(filter_diagnoses(["Ewing Sarcoma", "Neuroblastoma"]),
                         ["Ewing Sarcoma", "Neuroblastoma"])

    def test_everything_unknown_yields_empty(self):
        self.assertEqual(filter_diagnoses(["Leukemia"]), [])


class TestFilterGenomicCriteria(unittest.TestCase):
    def test_drops_the_invented_symbol_only(self):
        kept = filter_genomic_criteria(
            [_genomic(s) for s in ("H3", "H3-3A", "H3-3B", "H3C2")])
        self.assertEqual([e["genomic"]["hugo_symbol"] for e in kept],
                         ["H3-3A", "H3-3B", "H3C2"])

    def test_rewrites_case(self):
        kept = filter_genomic_criteria([_genomic("mycn")])
        self.assertEqual(kept[0]["genomic"]["hugo_symbol"], "MYCN")

    def test_negated_categories_are_untouched(self):
        kept = filter_genomic_criteria([_genomic("MYCN", "!Copy Number Variation")])
        self.assertEqual(kept[0]["genomic"]["variant_category"],
                         "!Copy Number Variation")

    def test_entry_without_a_symbol_is_left_for_the_completeness_checks(self):
        entry = {"genomic": {"variant_category": "Mutation"}}
        self.assertEqual(filter_genomic_criteria([entry]), [entry])

    def test_empty_input(self):
        self.assertEqual(filter_genomic_criteria([]), [])
        self.assertEqual(filter_genomic_criteria(None), [])


class TestDiagnosesFromConditions(unittest.TestCase):
    """
    conditionsModule is the trial stating its own diagnoses, and 27% of the
    cached corpus uses the exact Oncotree display name. Reading it costs no
    tokens and cannot hallucinate.
    """

    def test_exact_condition_is_taken(self):
        self.assertEqual(diagnoses_from_conditions(["Neuroblastoma"]),
                         ["Neuroblastoma"])

    def test_qualifiers_are_peeled(self):
        self.assertEqual(
            diagnoses_from_conditions(["High-Risk Neuroblastoma"]),
            ["Neuroblastoma"])
        self.assertEqual(
            diagnoses_from_conditions(["Recurrent Childhood Medulloblastoma"]),
            ["Medulloblastoma"])

    def test_a_real_node_beats_its_own_prefix(self):
        # "Primary" and "Malignant" are peelable qualifiers, but these are the
        # node names. The unmodified string is tried first for exactly this.
        self.assertEqual(diagnoses_from_conditions(["Primary Brain Tumor"]),
                         ["Primary Brain Tumor"])
        self.assertEqual(
            diagnoses_from_conditions(["Malignant Peripheral Nerve Sheath Tumor"]),
            ["Malignant Peripheral Nerve Sheath Tumor"])

    def test_non_diagnoses_yield_nothing(self):
        # The commonest condition strings are categories, not Oncotree nodes.
        self.assertEqual(diagnoses_from_conditions(
            ["Pediatric Cancer", "Solid Tumor", "Healthy Volunteers"]), [])

    def test_order_stable_and_deduplicated(self):
        self.assertEqual(
            diagnoses_from_conditions(
                ["Osteosarcoma", "Recurrent Osteosarcoma", "Ewing Sarcoma"]),
            ["Osteosarcoma", "Ewing Sarcoma"])

    def test_empty_input(self):
        self.assertEqual(diagnoses_from_conditions([]), [])
        self.assertEqual(diagnoses_from_conditions(None), [])

    def test_strip_is_idempotent(self):
        self.assertEqual(
            strip_condition_qualifiers("Recurrent Metastatic Childhood Melanoma"),
            "Melanoma")


class TestAnswerKeyIsNotDamaged(unittest.TestCase):
    """
    The validator must never drop something a human curator kept. The 17
    reviewed trials are the only ground truth available, so they gate it.
    """

    def test_every_reviewed_diagnosis_and_gene_survives(self):
        import glob
        import yaml

        def walk(node, want):
            if isinstance(node, dict):
                if want in node and isinstance(node[want], dict):
                    yield node[want]
                for value in node.values():
                    yield from walk(value, want)
            elif isinstance(node, list):
                for value in node:
                    yield from walk(value, want)

        paths = sorted(glob.glob(os.path.join(
            os.path.dirname(__file__), '..', 'ctml', 'reviewed', '*.yaml')))
        self.assertTrue(paths, "no reviewed trials found")
        rejected = []
        for path in paths:
            doc = yaml.safe_load(open(path))
            for step in (doc.get('treatment_list') or {}).get('step') or []:
                for match in step.get('match') or []:
                    for clinical in walk(match, 'clinical'):
                        term = clinical.get('oncotree_primary_diagnosis')
                        if term and canonical_diagnosis(term) is None:
                            rejected.append((os.path.basename(path), term))
                    for genomic in walk(match, 'genomic'):
                        symbol = genomic.get('hugo_symbol')
                        if symbol and canonical_gene(symbol) is None:
                            rejected.append((os.path.basename(path), symbol))
        self.assertEqual(rejected, [])


if __name__ == '__main__':
    unittest.main()
