"""
CTIS must take the same diagnosis path as ClinicalTrials.gov.

Until 2026-09-21 it did not: src/ctis.py called the eligibility mapper
directly with no seed, so a quarter of the corpus got no deterministic floor,
no branch forcing and no basket detection - and trial_map_manager saved the
result straight to the output directory, bypassing the review queue that
exists to stop a diagnosis-less trial matching every patient.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import src.clinical_trials_gov as ctg
import src.trial_map_manager as tmm

logger.remove()


class TestSharedSeeding(unittest.TestCase):
    def test_the_seed_is_returned_even_when_the_model_finds_nothing(self):
        with patch.object(ctg, 'map_eligibility_criteria_to_oncotree_term',
                          return_value=[]):
            seeded, from_eligibility = ctg.seed_and_map_diagnosis(
                '2023-500000-00-00', ['Neuroblastoma'], 'some criteria')
        self.assertEqual(seeded, ['Neuroblastoma'])
        self.assertEqual(from_eligibility, [])

    def test_the_seed_is_passed_to_the_model_as_a_floor(self):
        """
        The branch floor is the fix for the unreachable-answer trap: without a
        seed, a wrong level_1 makes the right diagnosis impossible to return.
        """
        with patch.object(ctg, 'map_eligibility_criteria_to_oncotree_term',
                          return_value=[]) as mapper:
            ctg.seed_and_map_diagnosis('2023-500000-00-00', ['Neuroblastoma'], 'text')
        self.assertEqual(mapper.call_args.args[2], ['Neuroblastoma'])

    def test_no_model_call_without_criteria(self):
        with patch.object(ctg, 'map_eligibility_criteria_to_oncotree_term') as mapper:
            seeded, from_eligibility = ctg.seed_and_map_diagnosis(
                '2023-500000-00-00', ['Neuroblastoma'], '')
        mapper.assert_not_called()
        self.assertEqual(seeded, ['Neuroblastoma'])

    def test_british_spelling_in_ctis_conditions_resolves(self):
        # CTIS is the European half of the corpus and spells it this way.
        seeded, _ = ctg.seed_and_map_diagnosis(
            '2023-507222-17-00', ['Acute Myeloid Leukaemia'], '')
        self.assertEqual(seeded, ['Acute Myeloid Leukemia'])

    def test_a_basket_keeps_its_wildcards_beside_named_entities(self):
        # NCT02332668, KEYNOTE-051: "solid malignancy or lymphoma", with
        # melanoma and classical Hodgkin lymphoma as named cohorts. Before the
        # union it kept the two entities and lost the basket.
        conditions = ['Melanoma', 'Lymphoma', 'Solid Tumor',
                      'Classical Hodgkin Lymphoma',
                      'Microsatellite-instability-high Solid Tumor']
        seeded, _ = ctg.seed_and_map_diagnosis('NCT02332668', conditions, '')
        self.assertIn('_SOLID_', seeded)
        # Union, not replacement: CHL is liquid, and _SOLID_ does not cover it.
        self.assertIn('Classical Hodgkin Lymphoma', seeded)
        self.assertIn('Melanoma', seeded)

    def test_the_model_floor_never_carries_wildcards(self):
        # The floor forces Oncotree branches; _SOLID_ is not a node.
        with patch.object(ctg, 'map_eligibility_criteria_to_oncotree_term',
                          return_value=[]) as mapper:
            seeded, _ = ctg.seed_and_map_diagnosis(
                'NCT02332668', ['Melanoma', 'Solid Tumor', 'Cancer'], 'text')
        self.assertIn('_SOLID_', seeded)
        self.assertEqual(mapper.call_args.args[2], ['Melanoma'])

    def test_a_category_header_adds_no_wildcard(self):
        # One umbrella term ahead of a list is a header, not a basket.
        seeded, _ = ctg.seed_and_map_diagnosis(
            'NCT04897321', ['Pediatric Solid Tumor', 'Osteosarcoma', 'Neuroblastoma'], '')
        self.assertFalse({'_SOLID_', '_LIQUID_'} & set(seeded))

    def test_basket_wildcards_are_reachable_publicly(self):
        self.assertEqual(ctg.basket_wildcards(['Pediatric Cancer']),
                         {'_SOLID_', '_LIQUID_'})


class TestCtisReviewRouting(unittest.TestCase):
    def test_a_ctis_trial_without_a_diagnosis_goes_to_the_review_queue(self):
        normal = os.path.join(os.path.dirname(__file__), 'ctml-out')
        destination = tmm.TrialMapManager._destination_for(
            {'match': [{'clinical': {'age_numerical': '>=1'}}]}, normal, '2023-500000-00-00')
        self.assertNotEqual(destination, normal)

    def test_a_ctis_trial_with_a_diagnosis_goes_to_the_normal_output(self):
        normal = os.path.join(os.path.dirname(__file__), 'ctml-out')
        destination = tmm.TrialMapManager._destination_for(
            {'match': [{'clinical': {'oncotree_primary_diagnosis': 'Neuroblastoma'}}]},
            normal, '2023-500000-00-00')
        self.assertEqual(destination, normal)


if __name__ == '__main__':
    unittest.main()
