"""
A gene the model returned that the trial's text does not name is kept, flagged
gene_unsupported, routed to review and reported in the index as gene_check.

The answers and text below are real: the Haiku 4.5 inclusion-genomic answer
for NCT06083883 (a synovial sarcoma / myxoid liposarcoma TCR trial) and
eligibility text from NCT06177067. NCT06083883 names its liposarcoma fusions
only in cytogenetic notation, t(12;16)(q13;p11) and t(12; 22) (q13;q12). With
that sentence the model's FUS::DDIT3 and EWSR1::DDIT3 are supported through
utils/translocations.py; without it they would be flagged. On the saved
answers for all 55 reviewed trials the flag falls on 1 gene in 1 trial per
replicate (FLI1 read from "EWSR1-Fli").
"""
import copy
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import utils.reference_validation as rv
from src.match_criteria_mapper import (_flag_unsupported_genes, _postprocess_genomic_criteria,
                                       convert_to_ctml_genomic_schema)
from src.trial_criteria_to_genes import TrialCriteriaToGenes
from src.trial_map_manager import TrialMapManager
from utils.build_trial_index import build

logger.remove()

# NCT06083883, inclusion criterion 2 without criterion 19a, i.e. a text that
# does not state the liposarcoma translocations.
NCT06083883_TEXT = (
    "2. Patients with histologically confirmed synovial sarcoma (cohort 1) or myxoid/round "
    "cell liposarcoma (cohort 2), with an HLA-A\\*02:01, HLA-A\\*02:05 or HLA-A\\*02:06 "
    "positive and a positive expression of NY-ESO-1 (\\>/= 50% tumor cells 2+ or 3+ by IHC). "
    "Diagnosis of synovial sarcoma with a confirmation by the presence of a translocation "
    "between SYT on the X chromosome and SSX1, SSX2 or SSX4")
# Criterion 19a, verbatim.
NCT06083883_19A = ("a. Patients must have histologically confirmed myxoid/round cell liposarcoma "
                   "with a confirmation by the presence of the reciprocal chromosomal translocation "
                   "t(12;16)(q13;p11) or t(12; 22) (q13;q12).")
NCT06083883_ANSWER = [
    {"genomic": {"hugo_symbol": "FUS", "variant_category": "Structural Variation",
                 "fusion_partner": "DDIT3"}},
    {"genomic": {"hugo_symbol": "EWSR1", "variant_category": "Structural Variation",
                 "fusion_partner": "DDIT3"}}]
NCT06177067_TEXT = ("NPM1 mutation or fusion, PICALM::MLLT10, DEK::NUP214, UBTF-TD, KAT6A "
                    "rearrangement (KAT6Ar), or SET::NUP214")


def _scan(text):
    return TrialCriteriaToGenes(text, rv.gene_synonym_mapping()).extract_official_gene_symbols()


class TestFlag(unittest.TestCase):

    def test_fusions_stated_as_translocations_are_supported(self):
        text = NCT06083883_TEXT + "\n" + NCT06083883_19A
        crit = _postprocess_genomic_criteria(copy.deepcopy(NCT06083883_ANSWER), "NCT06083883",
                                             _scan(text), text)
        self.assertEqual([c["genomic"].get("gene_unsupported") for c in crit], [None, None])

    def test_genes_the_text_does_not_state_are_flagged(self):
        crit = _postprocess_genomic_criteria(copy.deepcopy(NCT06083883_ANSWER), "NCT06083883",
                                             _scan(NCT06083883_TEXT), NCT06083883_TEXT)
        self.assertEqual([c["genomic"].get("gene_unsupported") for c in crit],
                         ["FUS, DDIT3", "EWSR1, DDIT3"])
        # Kept, not dropped: a curator decides.
        self.assertEqual([c["genomic"]["hugo_symbol"] for c in crit], ["FUS", "EWSR1"])

    def test_a_scanned_gene_is_not_flagged(self):
        crit = [{"genomic": {"hugo_symbol": "NUP214", "variant_category": "Structural Variation",
                             "fusion_partner": "DEK"}}]
        _flag_unsupported_genes(crit, _scan(NCT06177067_TEXT), NCT06177067_TEXT, "NCT06177067")
        self.assertNotIn("gene_unsupported", crit[0]["genomic"])

    def test_a_partner_written_verbatim_but_off_the_synonym_table_is_not_flagged(self):
        # SET is not in the synonym table, so the scan cannot find it, but the
        # text spells "SET::NUP214".
        self.assertNotIn("SET", _scan(NCT06177067_TEXT))
        crit = [{"genomic": {"hugo_symbol": "NUP214", "variant_category": "Structural Variation",
                             "fusion_partner": "SET"}}]
        _flag_unsupported_genes(crit, _scan(NCT06177067_TEXT), NCT06177067_TEXT, "NCT06177067")
        self.assertNotIn("gene_unsupported", crit[0]["genomic"])
        # Without the text it would have been flagged.
        _flag_unsupported_genes(crit, _scan(NCT06177067_TEXT), "", "NCT06177067")
        self.assertEqual(crit[0]["genomic"]["gene_unsupported"], "SET")

    def test_a_substring_is_not_a_mention(self):
        # "NUP214" must not support NUP21, nor "KAT6Ar" KAT6.
        crit = [{"genomic": {"hugo_symbol": "KAT6B", "variant_category": "Structural Variation"}}]
        _flag_unsupported_genes(crit, [], NCT06177067_TEXT, "NCT06177067")
        self.assertEqual(crit[0]["genomic"]["gene_unsupported"], "KAT6B")

    def test_no_scan_means_no_check(self):
        crit = _postprocess_genomic_criteria(copy.deepcopy(NCT06083883_ANSWER), "NCT06083883")
        self.assertFalse(any("gene_unsupported" in c["genomic"] for c in crit))

    def test_the_schema_converter_passes_the_scan_through(self):
        ctml = convert_to_ctml_genomic_schema(copy.deepcopy(NCT06083883_ANSWER), [],
                                              NCT06083883_TEXT, "", "NCT06083883",
                                              scanned_genes=_scan(NCT06083883_TEXT))
        leaves = ctml["or"] if "or" in ctml else [ctml]
        self.assertTrue(all("gene_unsupported" in leaf["genomic"] for leaf in leaves), ctml)


class TestRouting(unittest.TestCase):

    def _doc(self, genomic):
        return {"match": [{"and": [
            {"clinical": {"oncotree_primary_diagnosis": "Synovial Sarcoma"}},
            {"genomic": genomic}]}]}

    def test_an_unsupported_gene_goes_to_review(self):
        doc = self._doc({"hugo_symbol": "FUS", "variant_category": "Structural Variation",
                         "fusion_partner": "DDIT3", "gene_unsupported": "FUS, DDIT3"})
        self.assertEqual(TrialMapManager._destination_for(doc, "cache/ctml", "NCT06083883"),
                         config.CTML_REVIEW_PATH)

    def test_a_supported_gene_stays(self):
        doc = self._doc({"hugo_symbol": "SSX1", "variant_category": "Structural Variation"})
        self.assertEqual(TrialMapManager._destination_for(doc, "cache/ctml", "NCT06083883"),
                         "cache/ctml")


class TestIndex(unittest.TestCase):

    def _rows(self, genomic):
        source, out = tempfile.mkdtemp(), tempfile.mkdtemp()
        doc = {"nct_id": "NCT1", "treatment_list": {"step": [{"match": [{"and": [
            {"clinical": {"oncotree_primary_diagnosis": "Synovial Sarcoma"}},
            {"genomic": genomic}]}]}]}}
        with open(os.path.join(source, "NCT1.json"), "w") as handle:
            json.dump(doc, handle)
        build(source, out)
        with open(os.path.join(out, "trial_genomic.tsv")) as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_gene_check_reports_the_flag(self):
        rows = self._rows({"hugo_symbol": "EWSR1", "variant_category": "Structural Variation",
                           "fusion_partner": "DDIT3", "gene_unsupported": "EWSR1, DDIT3"})
        self.assertTrue(rows)
        self.assertEqual({r["gene_check"] for r in rows}, {"unsupported: EWSR1, DDIT3"})

    def test_gene_check_is_empty_otherwise(self):
        rows = self._rows({"hugo_symbol": "SSX1", "variant_category": "Structural Variation"})
        self.assertEqual(rows[0]["gene_check"], "")


if __name__ == "__main__":
    unittest.main()
