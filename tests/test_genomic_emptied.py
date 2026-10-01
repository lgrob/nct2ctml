import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import src.match_criteria_mapper as mcm
from src.trial_map_manager import TrialMapManager

logger.remove()


def _convert(inclusions, exclusions=(), inc_text="", exc_text="", trial_id="NCT0", scan=("BRAF",)):
    mcm.GENOMIC_EMPTIED.pop(trial_id, None)
    return mcm.convert_to_ctml_genomic_schema(
        list(inclusions), list(exclusions), inc_text, exc_text, trial_id, scanned_genes=list(scan)
    )


class TestGenomicEmptied(unittest.TestCase):
    """
    Every drop in convert_to_ctml_genomic_schema is defended as narrowing one
    criterion among several. When it takes the last one the genomic block
    disappears, combine_clinical_and_genomic_ctml falls through to the
    clinical criteria alone, and the trial is published matching every patient
    with the diagnosis - the alteration it requires asked of nobody. The
    emptied answer is recorded so the trial goes to review instead.
    """

    def test_a_dropped_last_criterion_is_recorded(self):
        # The alteration written into hugo_symbol: not a gene in ref/genes.txt,
        # so reference_validation.filter_genomic_criteria drops it.
        out = _convert(
            [{"genomic": {"hugo_symbol": "BRAF V600E", "variant_category": "Mutation"}}],
            inc_text="an oncogenic alteration in BRAF V600",
            trial_id="NCT_EMPTIED",
        )
        self.assertEqual(out, {})
        self.assertEqual(mcm.GENOMIC_EMPTIED.get("NCT_EMPTIED"), ["BRAF V600E"])

    def test_a_surviving_criterion_records_nothing(self):
        out = _convert(
            [{"genomic": {"hugo_symbol": "BRAF", "variant_category": "Mutation"}}],
            inc_text="an oncogenic alteration in BRAF V600",
            trial_id="NCT_KEPT",
        )
        self.assertEqual(out["genomic"]["hugo_symbol"], "BRAF")
        self.assertNotIn("NCT_KEPT", mcm.GENOMIC_EMPTIED)

    def test_a_model_that_returned_nothing_records_nothing(self):
        # A trial with no genomic criteria is not the same as one whose
        # criteria were dropped, and must not be sent to review.
        self.assertEqual(_convert([], trial_id="NCT_NONE"), {})
        self.assertNotIn("NCT_NONE", mcm.GENOMIC_EMPTIED)

    def test_the_record_reaches_the_ctml_and_routes_to_review(self):
        mcm.GENOMIC_EMPTIED["NCT_FLAG"] = ["BRAF V600E"]
        doc = {
            "nct_id": "NCT_FLAG",
            "treatment_list": {
                "step": [{"match": [{"clinical": {"oncotree_primary_diagnosis": "Melanoma"}}]}]
            },
        }
        TrialMapManager._record_genomic_emptied(doc, "NCT_FLAG")
        self.assertEqual(doc["genomic_emptied"], "BRAF V600E")
        self.assertEqual(
            TrialMapManager._destination_for(doc, "cache/ctml", "NCT_FLAG"),
            config.CTML_REVIEW_PATH,
        )


class TestMissingVariantCategory(unittest.TestCase):
    """
    The guard above the inclusion loop only asks that hugo_symbol and
    variant_category each appear somewhere in the model's list. A list where
    some items carry variant_category and others do not therefore reached a
    direct index and raised KeyError, which the callers catch as a mapping
    failure: the whole trial was lost, not just the item.
    """

    def test_a_mixed_list_keeps_the_complete_item(self):
        out = _convert(
            [
                {"genomic": {"hugo_symbol": "BRAF", "protein_change": "V600E"}},
                {"genomic": {"hugo_symbol": "BRAF", "variant_category": "Mutation"}},
            ],
            inc_text="an oncogenic alteration in BRAF V600",
            trial_id="NCT_MIXED",
        )
        self.assertEqual(out["genomic"]["hugo_symbol"], "BRAF")
        self.assertNotIn("NCT_MIXED", mcm.GENOMIC_EMPTIED)

    def test_a_list_with_no_variant_category_at_all_is_recorded(self):
        out = _convert(
            [{"genomic": {"hugo_symbol": "BRAF", "protein_change": "V600E"}}],
            inc_text="an oncogenic alteration in BRAF V600",
            trial_id="NCT_NOCAT",
        )
        self.assertEqual(out, {})
        self.assertEqual(mcm.GENOMIC_EMPTIED.get("NCT_NOCAT"), ["BRAF"])


class TestCohortCueIsAnchored(unittest.TestCase):
    """
    Case 2 of resolve_contradictory_genes drops both sides when the inclusion
    text negates the gene. The cue has to sit where the gene is named: tested
    against the whole inclusion text, the branch fired on unrelated prose -
    "without" occurs somewhere in the inclusion text of 18 of the 50 benchmark
    trials.
    """

    SIOPEN = (
        "Stage 2, 3, 4, 4s neuroblastoma with MYCN amplification, or stage 4 "
        "without MYCN amplification."
    )
    UNRELATED = (
        "Established diagnosis of neuroblastoma with MYCN amplification. "
        "Patients must be able to swallow capsules without assistance."
    )

    def _branch(self, inc_text):
        inc = [{"genomic": {"hugo_symbol": "MYCN", "variant_category": "Mutation"}}]
        exc = [{"genomic": {"hugo_symbol": "MYCN", "variant_category": "!Mutation"}}]
        kept_inc, kept_exc, notes = mcm.resolve_contradictory_genes(
            inc, exc, inc_text, "MYCN amplification"
        )
        return kept_inc, kept_exc, notes

    def test_a_cue_in_the_gene_sentence_still_drops_both(self):
        kept_inc, kept_exc, notes = self._branch(self.SIOPEN)
        self.assertEqual((kept_inc, kept_exc), ([], []))
        self.assertEqual(notes, ["MYCN: dropped both (alternative cohorts)"])

    def test_a_cue_elsewhere_keeps_the_stated_inclusion(self):
        kept_inc, kept_exc, notes = self._branch(self.UNRELATED)
        self.assertEqual(len(kept_inc), 1)
        self.assertEqual(kept_exc, [])
        self.assertEqual(notes, ["MYCN: dropped spurious exclusion"])

    def test_the_cue_may_sit_in_the_same_bullet(self):
        # Bullets, not only sentences: the eligibility text is mostly "* ..."
        text = "* L2 or M neuroblastoma, any age, without MYCN amplification\n* Age under 21"
        self.assertTrue(mcm._cohort_negation_near(text, "MYCN"))

    def test_a_cue_in_another_bullet_does_not_count(self):
        text = "* M neuroblastoma with MYCN amplification\n* Able to swallow without assistance"
        self.assertFalse(mcm._cohort_negation_near(text, "MYCN"))


if __name__ == "__main__":
    unittest.main()
