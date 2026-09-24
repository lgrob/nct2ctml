import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import config

from utils.oncotree import get_lineage
from utils.reference_validation import (
    _diagnosis_aliases,
    _widen_inferred_nos_leaf,
    _fold,
    _oncotree,
    _oncotree_folded,
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
        for alias in ("ALL", "AT", "ARF", "AGO", "H3", "AA", "ABL", "AKT", "CAR"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_multi_gene_aliases_are_not_rewritten(self):
        # "RAS" -> KRAS,NRAS,HRAS: no single symbol to rewrite to.
        for alias in ("RAS", "KRAS/NRAS/HRAS", "RAS-mutated"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_the_rewrite_set_holds_only_safe_shapes(self):
        """
        Replaces a cap of 40 entries, which pinned the renames-only set. The
        set is now ~4,000 synonym-table aliases, so what is pinned is its
        shape: every target a panel gene, every alias long enough or a Kispi
        rename, and none of them another gene's current symbol.
        """
        from utils.reference_validation import (
            _gene_aliases, _legacy_renames, _mane_genes, gene_symbols)
        genes = gene_symbols()
        renames = _legacy_renames(genes)
        other_genes = _mane_genes() - genes
        bad = [(a, g) for a, g in _gene_aliases().items()
               if g not in genes or a in genes
               or (a not in renames and (len(a) < 4 or a in other_genes))]
        self.assertEqual(bad, [])


class TestWidenedGeneRewrite(unittest.TestCase):
    """
    Roadmap 1.3: canonical_gene now rewrites unambiguous >=4-character aliases
    of a panel gene, not only the fifteen Kispi renames. Each refusal below is
    a class of alias measured to be wrong as a rewrite; see _panel_aliases and
    ref/gene_rewrite_exclusions.tsv.
    """

    def _clear(self):
        from utils.reference_validation import _gene_aliases
        _gene_aliases.cache_clear()
        canonical_gene.cache_clear()

    def test_retired_histone_spellings_resolve(self):
        """The motivating case: dropped before, although the table maps both."""
        for alias, current in (("HIST1H3A", "H3C1"), ("HIST2H3C", "H3C14"),
                               ("HIST1H3B", "H3C2"), ("HIST1H3C", "H3C3")):
            self.assertEqual(canonical_gene(alias), current, alias)

    def test_other_long_aliases_resolve(self):
        for alias, current in (("INI1", "SMARCB1"), ("CRAF", "RAF1"),
                               ("MEK1", "MAP2K1"), ("HER-2", "ERBB2")):
            self.assertEqual(canonical_gene(alias), current, alias)

    def test_the_addendum_blocklist_still_wins(self):
        """
        "!PD-L1" vetoes the NCBI row, and "PDL1" - the same alias without the
        hyphen, in 5 cached trials - must not slip past it to CD274. PD-L1 has
        its own biomarker path.
        """
        for alias in ("PD-L1", "PDL1", "pd-l1"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_ambiguous_aliases_never_resolve(self):
        # Multi-gene rows, and aliases dropped as collisions when the table
        # was built (ref/synonym_collisions.tsv).
        for alias in ("RAS", "BRCA", "NTRK", "BRCA1/2", "ALK1", "CDKN2", "FACD"):
            self.assertIsNone(canonical_gene(alias), alias)
        # Unambiguous only while case matters: p100 is NFKB2, P100 is PMEL.
        for alias in ("p100", "P100", "Delta", "DELTA", "Mip1", "MIP1"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_another_genes_symbol_is_not_hijacked(self):
        """TCF4 is a gene in its own right; the table lists it under TCF7L2."""
        from utils.reference_validation import fusion_partner
        for symbol in ("TCF4", "PDK1", "TTF1", "MST1", "CAST"):
            self.assertIsNone(canonical_gene(symbol), symbol)
        self.assertEqual(fusion_partner("TCF4"), ("TCF4", "off_panel"))

    def test_shape_rules_refuse(self):
        for alias in ("CD20", "CD117", "CD140a",   # antigens
                      "PARP", "HDAC", "VEGF", "PTCH", "PSMA",  # family stems
                      "BCR-ABL", "EWS-FLI1"):      # fusion names
            self.assertIsNone(canonical_gene(alias), alias)

    def test_observed_non_gene_usage_is_refused(self):
        """
        Each occurs in the cached eligibility texts meaning something else:
        JMML the disease (22 trials), CHOP the Children's Hospital of
        Philadelphia, ICF1 an informed consent form, ARM1 a trial arm, PD-1
        and CTLA-4 as prior-therapy targets.
        """
        for alias in ("JMML", "CHOP", "ICF1", "ARM1", "HLRCC", "WAGR", "PD-1",
                      "CTLA-4", "PD-L2", "OX40", "IL-2", "GMCSF", "VEGFR",
                      "B7-H3", "NY-ESO-1", "FACE", "TRAIL", "IRIS"):
            self.assertIsNone(canonical_gene(alias), alias)

    def test_every_exclusion_row_is_live(self):
        """
        A row the rules already refuse, or that is no longer an alias, is dead
        weight that misleads the next reader - the same honesty check the
        diagnosis synonym table has.
        """
        from utils.reference_validation import (
            _panel_aliases, _rewrite_exclusions, gene_symbols)
        rows = _rewrite_exclusions()
        with tempfile.NamedTemporaryFile('w', suffix='.tsv', delete=False) as handle:
            handle.write("# empty\n")
            path = handle.name
        try:
            with patch.object(config, 'GENE_REWRITE_EXCLUSION_FILE_PATH', path):
                unfiltered = _panel_aliases(gene_symbols())
        finally:
            os.unlink(path)
        self.assertTrue(rows)
        self.assertEqual(sorted(rows - set(unfiltered)), [])

    def test_a_missing_exclusion_list_fails_closed(self):
        """Without it JMML would reach PTPN11, so the widening switches off."""
        with patch.object(config, 'GENE_REWRITE_EXCLUSION_FILE_PATH',
                          '/nonexistent/gene_rewrite_exclusions.tsv'):
            self._clear()
            try:
                self.assertIsNone(canonical_gene("JMML"))
                self.assertIsNone(canonical_gene("HIST1H3A"))
                self.assertEqual(canonical_gene("H3F3A"), "H3-3A")
            finally:
                self._clear()

    def test_filter_rewrites_rather_than_drops(self):
        kept = filter_genomic_criteria(
            [{"genomic": {"hugo_symbol": "HIST1H3A", "variant_category": "Mutation"}},
             {"genomic": {"hugo_symbol": "JMML", "variant_category": "Mutation"}}])
        self.assertEqual([e["genomic"]["hugo_symbol"] for e in kept], ["H3C1"])


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

    def test_trailing_qualifiers_are_peeled(self):
        # ClinicalTrials.gov puts the qualifier after the diagnosis at least as
        # often as before it.
        for condition, expected in (
                ("Medulloblastoma Recurrent", "Medulloblastoma"),
                ("Ependymoma Recurrent", "Ependymoma"),
                ("Medulloblastoma, Childhood", "Medulloblastoma"),
                ("Neuroblastoma, Recurrent, Refractory", "Neuroblastoma"),
                ("Recurrent Childhood Medulloblastoma, Refractory", "Medulloblastoma")):
            self.assertEqual(strip_condition_qualifiers(condition), expected, condition)

    def test_trailing_strip_resolves_real_conditions(self):
        self.assertEqual(diagnoses_from_conditions(["Medulloblastoma Recurrent"]),
                         ["Medulloblastoma"])
        # A code survives the peel and still resolves to its display name.
        self.assertEqual(diagnoses_from_conditions(["ATRT Recurrent"]),
                         ["Atypical Teratoid/Rhabdoid Tumor"])

    def test_a_node_ending_in_a_qualifier_word_matches_as_itself(self):
        # Several Oncotree names end in "NOS", which the trailing rule would
        # strip. The unmodified string is tried first for exactly this reason.
        for name in ("B-Lymphoblastic Leukemia/Lymphoma, NOS",
                     "Mixed Phenotype Acute Leukemia, B/Myeloid, NOS",
                     "High-Grade B-Cell Lymphoma, NOS",
                     "Astrocytoma, IDH-Mutant, Grade 3"):
            self.assertEqual(diagnoses_from_conditions([name]), [name], name)


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


class TestNosFallback(unittest.TestCase):
    """
    Oncotree suffixes its catch-all nodes with ", NOS" and registries do not,
    so a trial registering "Low-grade Glioma" names a node an exact match
    cannot find. The fallback is tried last, which is what keeps it from
    over-generating.
    """

    def test_catch_all_conditions_now_resolve(self):
        """
        "Glioma" used to assert "Glioma, NOS" here and now asserts "Diffuse
        Glioma". The leaf expands to one patient code and its parent to 24, so
        the old expectation named a term that matched almost nobody. The other
        three still resolve to their leaf: each states a qualifier its parent
        drops, so widening them would change the population. See
        TestNosWidening.
        """
        for condition, expected in (
            ("Low-grade Glioma", "Low-Grade Glioma, NOS"),
            ("Glioma", "Diffuse Glioma"),
            ("High-grade Glioma", "High-Grade Glioma, NOS"),
            ("Round Cell Sarcoma", "Round Cell Sarcoma, NOS"),
        ):
            self.assertEqual(diagnoses_from_conditions([condition]), [expected],
                             condition)

    def test_an_exact_node_does_not_also_collect_its_nos_sibling(self):
        """
        The ordering is the whole guard. Tried first, ", NOS" would give
        "Medulloblastoma" both the exact node and "Medulloblastoma, NOS", and
        the seed would over-generate instead of reaching further.
        """
        self.assertEqual(diagnoses_from_conditions(["Medulloblastoma"]),
                         ["Medulloblastoma"])
        self.assertEqual(diagnoses_from_conditions(["Neuroblastoma"]),
                         ["Neuroblastoma"])

    def test_it_composes_with_qualifier_stripping(self):
        self.assertEqual(diagnoses_from_conditions(["Pediatric Sarcoma, Refractory"]),
                         ["Sarcoma, NOS"])

    def test_it_invents_nothing(self):
        for condition in ("Neoplasms, Brain", "Asthma", "Healthy Volunteers", ""):
            self.assertEqual(diagnoses_from_conditions([condition]), [], condition)


class TestGeneSynonymMapping(unittest.TestCase):
    """
    The input side of the gene reference. One loader now serves both this and
    canonical_gene; before that, TrialMapManager and three tests each had
    their own copy and only one applied the addendum's "!" blocklist.
    """

    def setUp(self):
        from utils.reference_validation import gene_synonym_mapping
        self.mapping = gene_synonym_mapping()

    def test_blocklisted_alias_is_absent(self):
        """
        "!PD-L1" in the addendum vetoes the NCBI row PD-L1 -> CD274. PD-L1 has
        its own biomarker path in the CTML schema, so resolving it as a gene
        would route the same criterion twice.
        """
        self.assertNotIn("PD-L1", self.mapping)
        self.assertNotIn("!PD-L1", self.mapping,
                         "the marker itself must not become a searchable term")

    def test_blocklist_is_applied_on_the_validation_side_too(self):
        from utils.reference_validation import canonical_gene
        self.assertIsNone(canonical_gene("PD-L1"))

    def test_ordinary_aliases_still_resolve(self):
        for alias, official in (("HER2", "ERBB2"), ("p53", "TP53"),
                                ("WHSC1", "NSD2")):
            self.assertIn(official, self.mapping.get(alias, []), alias)

    def test_multi_gene_rows_arrive_intact(self):
        """The caller splits these, not the loader."""
        self.assertEqual(self.mapping["RAS"], ["KRAS,NRAS,HRAS"])

    def test_it_is_the_permissive_table(self):
        """
        Deliberately unlike canonical_gene: a short alias belongs here, where
        a false positive costs one LLM call, and not there, where it would
        invent a criterion.
        """
        self.assertIn("ALL", self.mapping)
        self.assertIsNone(canonical_gene("ALL"))


class TestSingleReader(unittest.TestCase):
    def test_no_module_opens_the_gene_files_directly(self):
        """
        reference_validation is the only reader. Six files used to spell these
        paths as literals, which is how the blocklist came to be honoured in
        one place and ignored in another.
        """
        import glob
        root = os.path.join(os.path.dirname(__file__), '..')
        offenders = []
        for path in glob.glob(os.path.join(root, '*/*.py')) + glob.glob(os.path.join(root, '*.py')):
            rel = os.path.relpath(path, root)
            # config.py is where the paths belong; build_gene_synonyms.py
            # writes the tables rather than reading them; this file names them
            # in its own assertions.
            if rel.startswith(('utils/reference_validation', 'utils/build_gene_synonyms',
                               'config.py', '.venv')) or rel == os.path.relpath(__file__, root):
                continue
            text = open(path).read()
            for literal in ('ref/genes.txt', 'ref/genes_kispi.txt',
                            'ref/synonym_to_gene_symbol.tsv',
                            'ref/gene_synonym_addendum.tsv',
                            'ref/gene_rewrite_exclusions.tsv'):
                if f'"{literal}"' in text or f"'{literal}'" in text:
                    offenders.append(f"{rel}: {literal}")
        self.assertEqual(offenders, [])


class TestFolding(unittest.TestCase):
    """
    Punctuation and British spelling are not medicine.

    Every case here is a real condition string from the cached corpus that
    used to return None and fall through to the LLM, which then had to pick
    an Oncotree branch unaided - the step that makes neuroblastoma land under
    Adrenal Gland. A hyphen should not cost a diagnosis.
    """

    def test_hyphen_is_forgiven(self):
        # NCT04655404 registers "High Grade Glioma".
        self.assertEqual(canonical_diagnosis("High Grade Glioma, NOS"),
                         "High-Grade Glioma, NOS")

    def test_apostrophe_is_forgiven(self):
        # NCT04322318 registers "... Kidney Wilms Tumor", never "Wilms'".
        self.assertEqual(canonical_diagnosis("Wilms Tumor"), "Wilms' Tumor")

    def test_slash_and_hyphen_are_interchangeable(self):
        self.assertEqual(canonical_diagnosis("B Lymphoblastic Leukemia Lymphoma"),
                         "B-Lymphoblastic Leukemia/Lymphoma")

    def test_british_spelling_is_forgiven(self):
        # The CTIS half of the corpus is European.
        self.assertEqual(canonical_diagnosis("Wilms Tumour"), "Wilms' Tumor")
        self.assertEqual(canonical_diagnosis("Acute Myeloid Leukaemia"),
                         "Acute Myeloid Leukemia")

    def test_commas_are_load_bearing_and_survive(self):
        # "Glioma, NOS" and "Glioma" are different nodes; folding must not
        # merge them, or a catch-all would answer for a specific tumour.
        self.assertNotEqual(_fold("Glioma, NOS"), _fold("Glioma"))

    def test_folding_invents_nothing(self):
        self.assertIsNone(canonical_diagnosis("Not A Disease"))
        self.assertIsNone(canonical_diagnosis("Cancer"))

    def test_folding_is_injective_over_the_whole_tree(self):
        """
        No two Oncotree display names may fold to the same key.

        True of oncotree_2025_10_03 (879 names, 879 keys). This asserts it
        rather than trusting it: a future release could introduce a pair
        distinguished only by a hyphen, and folding would then silently pick
        one. That must fail here, loudly, not in a patient's match list.
        """
        names, _, _ = _oncotree()
        self.assertEqual(len(_oncotree_folded()), len(names))


class TestDiagnosisAliases(unittest.TestCase):
    def test_lineage_is_resolved(self):
        # Oncotree has no lineage-free ALL node, so a lineage must be chosen.
        self.assertEqual(canonical_diagnosis("Acute Lymphoblastic Leukemia"),
                         "B-Lymphoblastic Leukemia/Lymphoma")
        self.assertEqual(canonical_diagnosis("T-Cell Acute Lymphoblastic Leukemia"),
                         "T-Lymphoblastic Leukemia/Lymphoma")

    def test_who_reclassification_is_resolved(self):
        # WHO CNS5 retired DIPG; our Oncotree carries only the successor.
        self.assertEqual(canonical_diagnosis("Diffuse Intrinsic Pontine Glioma"),
                         "Diffuse Midline Glioma, H3 K27-Altered")
        self.assertEqual(canonical_diagnosis("Diffuse Midline Glioma, H3 K27M-Mutant"),
                         "Diffuse Midline Glioma, H3 K27-Altered")

    def test_european_name_is_resolved(self):
        self.assertEqual(canonical_diagnosis("Nephroblastoma"), "Wilms' Tumor")

    def test_the_bare_all_abbreviation_is_not_an_alias(self):
        """
        Three-character aliases are how the gene table went wrong.

        "ALL" is left unresolved on purpose: a condition list containing only
        it should reach the review queue rather than be guessed at.
        """
        self.assertIsNone(canonical_diagnosis("ALL"))

    def test_every_alias_targets_a_real_oncotree_node(self):
        names, _, _ = _oncotree()
        for alias, target in _diagnosis_aliases().items():
            self.assertIn(target, names, f"{alias} targets a non-existent node")

    def test_no_alias_shadows_a_real_oncotree_name(self):
        """
        The table may only reach what the tree cannot.

        An alias whose own name already resolves is dead weight that cannot
        fire, and it would mislead the next person editing the file.
        """
        folded = _oncotree_folded()
        for alias in _diagnosis_aliases():
            self.assertNotIn(alias, folded)

    def test_a_row_with_an_unknown_target_is_dropped(self):
        """
        A typo in the table must not put an unmatchable string into CTML.

        This is the failure the whole module exists to prevent: CTML matching
        is on exact strings, so a target that is not an Oncotree node matches
        no patient and reads as a correct answer in the log.
        """
        with tempfile.NamedTemporaryFile('w', suffix='.tsv', delete=False) as handle:
            handle.write("# comment row\n")
            handle.write("Some Registry Name\tNot An Oncotree Node\twhy\n")
            handle.write("Nephroblastoma\tWilms' Tumor\twhy\n")
            path = handle.name
        try:
            with patch.object(config, 'DIAGNOSIS_SYNONYM_FILE_PATH', path):
                _diagnosis_aliases.cache_clear()
                aliases = _diagnosis_aliases()
            self.assertNotIn(_fold("Some Registry Name"), aliases)
            self.assertEqual(aliases.get(_fold("Nephroblastoma")), "Wilms' Tumor")
        finally:
            os.unlink(path)
            _diagnosis_aliases.cache_clear()
            canonical_diagnosis.cache_clear()

    def test_a_missing_table_is_survivable(self):
        """Folding must still work if the file is absent."""
        with patch.object(config, 'DIAGNOSIS_SYNONYM_FILE_PATH',
                          '/nonexistent/diagnosis_synonyms.tsv'):
            _diagnosis_aliases.cache_clear()
            try:
                self.assertEqual(_diagnosis_aliases(), {})
                self.assertEqual(canonical_diagnosis("Wilms Tumor"), "Wilms' Tumor")
            finally:
                _diagnosis_aliases.cache_clear()
                canonical_diagnosis.cache_clear()


class TestExtendedQualifiers(unittest.TestCase):
    def test_ajcc_staging_citation_is_stripped(self):
        # NCI appends the staging manual to its germ cell conditions.
        self.assertEqual(
            strip_condition_qualifiers("Stage I Testicular Seminoma AJCC v6 and v7"),
            "Testicular Seminoma")

    def test_substage_letters_are_stripped(self):
        self.assertEqual(strip_condition_qualifiers("Stage IIIB Osteosarcoma"),
                         "Osteosarcoma")

    def test_bare_relapse_noun_is_stripped(self):
        # NCT05366218 registers "Acute Lymphoid Leukemia Relapse".
        self.assertEqual(strip_condition_qualifiers("Acute Lymphoid Leukemia Relapse"),
                         "Acute Lymphoid Leukemia")

    def test_a_real_node_still_beats_stripping(self):
        """
        Stripping is a fallback; the unmodified string is tried first.

        Both of these begin with a word the leading-qualifier regex removes,
        and both are real nodes: "Malignant ..." would otherwise become
        "Peripheral Nerve Sheath Tumor" and "Primary CNS Melanoma" would
        become "CNS Melanoma", neither of which is what the trial said.
        """
        self.assertEqual(canonical_diagnosis("Malignant Peripheral Nerve Sheath Tumor"),
                         "Malignant Peripheral Nerve Sheath Tumor")
        self.assertEqual(canonical_diagnosis("Primary CNS Melanoma"),
                         "Primary CNS Melanoma")


class TestConditionSeedRegressions(unittest.TestCase):
    """
    The condition lists these trials actually register, verbatim.

    Each returned nothing before this change, so the trial's diagnosis was
    left entirely to the LLM.
    """

    def test_nci_wilms_house_style(self):
        self.assertEqual(
            diagnoses_from_conditions([
                'Anaplastic Kidney Wilms Tumor', 'Recurrent Kidney Wilms Tumor',
                'Stage II Kidney Wilms Tumor']),
            ["Wilms' Tumor"])

    def test_paediatric_all(self):
        self.assertEqual(
            diagnoses_from_conditions(['Acute Lymphoblastic Leukemia, Pediatric']),
            ['B-Lymphoblastic Leukemia/Lymphoma'])

    def test_all_spelling_variants_collapse_to_one_term(self):
        self.assertEqual(
            diagnoses_from_conditions([
                'ALL, Childhood B-Cell', 'Acute Lymphoid Leukemia Relapse',
                'Acute Lymphocytic Leukemia Refractory']),
            ['B-Lymphoblastic Leukemia/Lymphoma'])

    def test_retired_dipg_maps_to_its_successor(self):
        self.assertEqual(
            diagnoses_from_conditions([
                'Diffuse Intrinsic Pontine Glioma',
                'Diffuse Midline Glioma, H3 K27M-Mutant',
                'Recurrent Diffuse Intrinsic Pontine Glioma']),
            ['Diffuse Midline Glioma, H3 K27-Altered'])

    def test_unhyphenated_high_grade_glioma(self):
        self.assertEqual(
            diagnoses_from_conditions(['High Grade Glioma']),
            ['High-Grade Glioma, NOS'])


class TestNosWidening(unittest.TestCase):
    """
    An inferred ", NOS" leaf matches one patient code; its parent may match
    dozens. MatchMiner expands a diagnosis to its descendants before querying,
    so the leaf is a silent false negative - the trial looks curated and
    enrols nobody.
    """

    def test_a_true_catch_all_is_widened(self):
        # "Glioma, NOS" expands to 1 code, "Diffuse Glioma" to 24.
        self.assertEqual(diagnoses_from_conditions(["Glioma"]), ["Diffuse Glioma"])

    def test_widening_never_drops_a_stated_qualifier(self):
        """
        The guard that keeps this safe.

        "High-Grade Glioma, NOS" sits under "Diffuse Glioma", which includes
        low-grade entities, so widening would enrol low-grade patients into a
        high-grade trial. "Low-Grade Glioma, NOS" sits under "Encapsulated
        Glioma", which is not where low-grade gliomas generally live.
        """
        self.assertEqual(diagnoses_from_conditions(["High Grade Glioma"]),
                         ["High-Grade Glioma, NOS"])
        self.assertEqual(diagnoses_from_conditions(["Low Grade Glioma"]),
                         ["Low-Grade Glioma, NOS"])

    def test_widening_stops_below_the_organ_system_root(self):
        """
        "Sarcoma, NOS" hangs directly off the "Soft Tissue" root. Promoting it
        would enrol every soft-tissue tumour and still miss the bone sarcomas
        a sarcoma trial means, so the leaf is kept and logged instead.
        """
        self.assertEqual(diagnoses_from_conditions(["Sarcoma"]), ["Sarcoma, NOS"])

    def test_a_trial_that_says_nos_itself_is_respected(self):
        """
        Widening applies only to the suffix this code adds. If the trial wrote
        ", NOS", that is the curator's word, not an inference.
        """
        self.assertEqual(diagnoses_from_conditions(["Glioma, NOS"]), ["Glioma, NOS"])

    def test_the_verified_b_all_case(self):
        """
        The parent-beats-NOS case confirmed against two loaded MatchMiner
        trials: the parent expands to 8 terms including the leaf, the leaf to
        itself, and patients are coded with the parent.
        """
        self.assertEqual(
            canonical_diagnosis("B-Lymphoblastic Leukemia/Lymphoma, NOS"),
            "B-Lymphoblastic Leukemia/Lymphoma, NOS")
        self.assertEqual(
            diagnoses_from_conditions(["B-Lymphoblastic Leukemia/Lymphoma"]),
            ["B-Lymphoblastic Leukemia/Lymphoma"])

    def test_widening_only_ever_reaches_a_real_node(self):
        parent_of, level_1_names, descendants = get_lineage()
        for leaf in (n for n in descendants if n.endswith(", NOS")):
            widened = _widen_inferred_nos_leaf(leaf, leaf)
            self.assertIn(widened, descendants, leaf)

    def test_widening_never_reaches_an_organ_system_root(self):
        parent_of, level_1_names, descendants = get_lineage()
        for leaf in (n for n in descendants if n.endswith(", NOS")):
            self.assertNotIn(_widen_inferred_nos_leaf(leaf, leaf), level_1_names, leaf)


if __name__ == '__main__':
    unittest.main()
