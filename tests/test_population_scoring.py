"""
The benchmark's population metric: two diagnosis sets are the same answer
when they reach the same patients, and a patient is coded at the most
specific Oncotree node the pathology supports.

Every case here is one the name-based metric got wrong on the curated key.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bench.benchmark_map import population_prf, prf
from utils.build_trial_index import _population_reference, diagnosis_population
from utils.oncotree import get_lineage

B_ALL = "B-Lymphoblastic Leukemia/Lymphoma"
B_ALL_NOS = "B-Lymphoblastic Leukemia/Lymphoma, NOS"


class TestCodableNodes(unittest.TestCase):

    def setUp(self):
        self.parent, _, self.descendants = get_lineage()
        _, self.codable, self.solid, self.liquid = _population_reference()

    def test_parent_with_nos_child_is_not_codable(self):
        # A B-ALL patient who cannot be subtyped is coded to the NOS leaf.
        self.assertIn(B_ALL_NOS, self.codable)
        self.assertNotIn(B_ALL, self.codable)

    def test_internal_node_without_nos_child_is_codable(self):
        # Oncotree has no "Osteosarcoma, NOS"; the unsubtyped patient is coded
        # Osteosarcoma, so the parent itself is a patient code.
        self.assertGreater(len(self.descendants["Osteosarcoma"]), 1)
        self.assertIn("Osteosarcoma", self.codable)

    def test_only_nos_parents_are_excluded(self):
        excluded = set(self.descendants) - self.codable
        self.assertEqual(excluded,
                         {self.parent[n] for n in self.parent if n.endswith(", NOS")})

    def test_wildcards_partition_the_codable_nodes(self):
        solid = diagnosis_population({"_SOLID_"})
        liquid = diagnosis_population({"_LIQUID_"})
        self.assertFalse(solid & liquid)
        self.assertEqual(solid | liquid, set(self.codable))


class TestPopulationScore(unittest.TestCase):

    def test_redundant_enumeration_is_the_same_answer(self):
        # NCT04625907: the key lists Rhabdomyosarcoma and its subtypes, the
        # pipeline the parent alone. By name 0.40; by population identical.
        subtypes = set(get_lineage()[2]["Rhabdomyosarcoma"])
        self.assertLess(prf({"Rhabdomyosarcoma"}, subtypes)[2], 1.0)
        p, r, f, _, _ = population_prf({"Rhabdomyosarcoma"}, subtypes)
        self.assertEqual((p, r), (1.0, 1.0))

    def test_nos_leaf_for_parent_is_a_recall_loss_not_a_zero(self):
        p, r, _, reached, wanted = population_prf({B_ALL_NOS}, {B_ALL})
        self.assertEqual(p, 1.0)
        self.assertAlmostEqual(r, 1 / len(wanted))
        self.assertEqual(reached, {B_ALL_NOS})

    def test_overbroad_parent_is_a_precision_loss(self):
        p, r, _, _, _ = population_prf({"Myeloid"}, {"Acute Myeloid Leukemia"})
        self.assertEqual(r, 1.0)
        self.assertLess(p, 0.5)

    def test_specific_terms_for_a_basket_are_a_recall_loss(self):
        # NCT07440290's shape: the key is tumour-agnostic, the output names
        # one entity. By name this is 0.0 either way; by population it says
        # how much of the basket is lost.
        p, r, _, _, _ = population_prf({"Melanoma"}, {"_SOLID_"})
        self.assertEqual(p, 1.0)
        self.assertLess(r, 0.05)

    def test_empty_against_empty_agrees(self):
        self.assertEqual(population_prf(set(), set())[:3], (1.0, 1.0, 1.0))

    def test_unknown_term_matches_only_itself(self):
        self.assertEqual(diagnosis_population({"Not An Oncotree Node"}),
                         {"Not An Oncotree Node"})


if __name__ == "__main__":
    unittest.main()
