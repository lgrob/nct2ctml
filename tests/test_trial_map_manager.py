import os
import sys
import unittest

# Add the src directory to the path so we can import the module
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))


class TestTrialMapManager(unittest.TestCase):
    def setUp(self):
        from trial_map_manager import TrialMapManager

        self.manager = TrialMapManager()

    def test_get_gene_synonym_mapping(self):
        expected_mapping = {"p53": ["TP53"]}
        actual_mapping = self.manager.get_gene_synonym_mapping()
        for key in expected_mapping:
            self.assertIn(key, actual_mapping)
            self.assertNotIn("PD-L1", actual_mapping)


if __name__ == "__main__":
    unittest.main()
