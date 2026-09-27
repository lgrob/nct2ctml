"""Bracketed gene abbreviations joined to their number (2026-09-27)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import utils.gene_mentions as gm


class TestBracketedStems(unittest.TestCase):

    def test_joined(self):
        self.assertEqual(gm.join_bracketed_stems("isocitrate dehydrogenase (IDH) 1/2 mutation"), "isocitrate dehydrogenase IDH1/2 mutation")
        self.assertEqual(gm.join_bracketed_stems("kinase inhibitor (CDKN)2A/B deletion"), "kinase inhibitor CDKN2A/B deletion")

    def test_list_numbers_years_and_drug_classes_untouched(self):
        for s in ("plasma cell leukemia (PCL) 3. History", "European LeukemiaNet (ELN) 2022",
                  "cyclin-dependent kinase (CDK) 4 and 6 inhibitors"):
            self.assertEqual(gm.join_bracketed_stems(s), s)


if __name__ == "__main__":
    unittest.main()
