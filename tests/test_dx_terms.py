"""Diagnosis text matching knows clinical names, abbreviations and plurals (2026-09-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.review_helper as rh

logger.remove()


class TestDxTerms(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ref = rh.Reference()

    def test_nopho_exclusions_are_found(self):
        # 2024-518254-16-00: APL, MDS and ML-DS were not found before.
        exc = ("3. Down syndrome (DS). Patients with myeloid leukaemia of Down syndrome ... "
               "4. Acute promyelocytic leukaemia (APL). 5. Myelodysplastic syndrome (MDS). 6. JMML")
        dx = ["Acute Myeloid Leukemia", "APL with PML-RARA", "Myelodysplastic Syndromes",
              "Myeloid Leukemia Associated with Down Syndrome", "Juvenile Myelomonocytic Leukemia"]
        got = rh.diagnoses_only_in_exclusions(dx, "AML as defined by the protocol", exc, ref=self.ref)
        self.assertEqual(set(got), set(dx[1:]))

    def test_plural_and_apostrophe(self):
        self.assertTrue(rh.find_mentions("unilateral Wilms tumour", self.ref.dx_terms("Wilms' Tumor")))
        self.assertTrue(rh.find_mentions("a myelodysplastic syndrome", self.ref.dx_terms("Myelodysplastic Syndromes")))

    def test_short_abbreviations_are_case_sensitive(self):
        self.assertTrue(rh.find_mentions("relapsed T-ALL", self.ref.dx_terms("T-Lymphoblastic Leukemia/Lymphoma")))
        self.assertFalse(rh.find_mentions("a cml of fluid", self.ref.dx_terms("Chronic Myeloid Leukemia, BCR-ABL1+")))

    def test_every_row_names_an_oncotree_node(self):
        self.assertTrue(self.ref.text_terms)
        self.assertEqual([n for n in self.ref.text_terms if n not in self.ref.names], [])


if __name__ == "__main__":
    unittest.main()
