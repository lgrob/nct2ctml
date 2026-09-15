import json
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import src.clinical_trials_gov as ctg

logger.remove()  # the rule logs every decision; tests assert on return values


def _cached(nct_id):
    path = os.path.join(os.path.dirname(__file__), "..", "cache", "nct", f"{nct_id}.json")
    if not os.path.exists(path):
        return None
    return json.load(open(path))["protocolSection"]["conditionsModule"]["conditions"]


class TestBasketWildcards(unittest.TestCase):
    """
    A broad condition makes a trial a basket only when the trial names no
    specific diagnosis. Registries file a category header beside the real
    diagnoses often enough - 31 of the 104 cached trials with a broad term -
    that taking the header at face value replaces a precise answer with
    _SOLID_, which matches every solid-tumour patient in the database.
    """

    def test_broad_term_alone_is_a_basket(self):
        self.assertEqual(ctg._basket_wildcards(["Pediatric Cancer"]),
                         {"_SOLID_", "_LIQUID_"})
        self.assertEqual(ctg._basket_wildcards(["Advanced Solid Tumor"]), {"_SOLID_"})

    def test_broad_term_beside_a_named_diagnosis_is_a_header(self):
        self.assertEqual(
            ctg._basket_wildcards(["Pediatric Solid Tumor", "Osteosarcoma",
                                   "Neuroblastoma"]),
            set())

    def test_no_broad_term_is_never_a_basket(self):
        self.assertEqual(ctg._basket_wildcards(["Neuroblastoma"]), set())
        self.assertEqual(ctg._basket_wildcards([]), set())
        self.assertEqual(ctg._basket_wildcards(None), set())

    def test_liquid_only_appears_for_the_any_cancer_wording(self):
        """
        "Solid Tumor" justifies _SOLID_ alone; "Cancer" justifies both. Adding
        _LIQUID_ to a solid-tumour basket would match every leukaemia patient.
        """
        self.assertNotIn("_LIQUID_", ctg._basket_wildcards(["Solid Tumor"]))
        self.assertIn("_LIQUID_", ctg._basket_wildcards(["Cancer"]))


class TestSeveralUmbrellaTerms(unittest.TestCase):
    """
    A registry lists ONE umbrella term as a header for its list. A trial that
    registers several different ways of saying "any malignancy" is not heading
    a list, it is describing an unrestricted population.
    """

    def test_two_umbrella_terms_outweigh_a_named_diagnosis(self):
        self.assertEqual(
            ctg._basket_wildcards(["Malignant Neoplasm", "Cancer", "Glioma",
                                   "Erdheim-Chester Disease"]),
            {"_SOLID_", "_LIQUID_"})

    def test_one_umbrella_term_is_still_a_header(self):
        self.assertEqual(
            ctg._basket_wildcards(["Pediatric Solid Tumor", "Osteosarcoma",
                                   "Neuroblastoma"]),
            set())

    def test_the_threshold_is_named_not_magic(self):
        self.assertEqual(ctg._BASKET_BROAD_TERMS, 2)


class TestBasketWildcardsOnRealTrials(unittest.TestCase):
    """The trials that motivated the rule, read from the cached records."""

    def test_genuine_baskets(self):
        # NCT07440290 is the one this rule got wrong at first: a
        # tumour-agnostic dabrafenib arm registering "Malignant Neoplasm",
        # "Cancer" and "Solid Tumour" among twenty conditions. Reading its two
        # resolvable ones as the answer produced 55 diagnoses.
        for nct_id, expected in (("NCT02813135", {"_SOLID_", "_LIQUID_"}),
                                 ("NCT04094610", {"_SOLID_"}),
                                 ("NCT07440290", {"_SOLID_", "_LIQUID_"})):
            conditions = _cached(nct_id)
            if conditions is None:
                self.skipTest(f"{nct_id} not cached")
            self.assertEqual(ctg._basket_wildcards(conditions, nct_id), expected, nct_id)

    def test_category_headers_are_not_baskets(self):
        # NCT04897321 lists "Pediatric Solid Tumor" ahead of five real
        # diagnoses; NCT05918640 lists "Pediatric Cancer" beside Ewing sarcoma.
        for nct_id in ("NCT04897321", "NCT05918640"):
            conditions = _cached(nct_id)
            if conditions is None:
                self.skipTest(f"{nct_id} not cached")
            self.assertEqual(ctg._basket_wildcards(conditions, nct_id), set(), nct_id)


if __name__ == '__main__':
    unittest.main()
