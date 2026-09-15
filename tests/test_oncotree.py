import unittest
from pprint import pprint

import utils.oncotree as ot
import utils.reference_validation as rv
from utils.oncotree import (
    _get_level_columns,
    _parse_level_value,
    _read_oncotree_rows,
    get_all_oncotree_data,
    get_l1_l2_oncotree_data,
)


class TestOncotree(unittest.TestCase):

    def test_get_level_columns(self):
        fieldnames = ["level_3", "level_1", "metamaintype", "level_2"]
        self.assertEqual(_get_level_columns(fieldnames), ["level_1", "level_2", "level_3"])

    def test_parse_level_value(self):
        self.assertEqual(_parse_level_value("Breast (BREAST)"), "Breast")

    def test_parse_level_value_keeps_brackets_inside_the_name(self):
        """
        Only the trailing Oncotree code is stripped. Splitting on the first
        "(" truncated the twenty nodes whose display name has a parenthesis
        of its own, and merged those that shared a prefix.
        """
        for raw, expected in (
            ("B-Lymphoblastic Leukemia/Lymphoma with t(9;22)(q34.1;q11.2);BCR-ABL1 (BLLBCRABL1)",
             "B-Lymphoblastic Leukemia/Lymphoma with t(9;22)(q34.1;q11.2);BCR-ABL1"),
            ("AML with t(8;21)(q22;q22.1);RUNX1-RUNX1T1 (AMLRUNX1RUNX1T1)",
             "AML with t(8;21)(q22;q22.1);RUNX1-RUNX1T1"),
            ("Primary Mediastinal (Thymic) Large B-Cell Lymphoma (PMBL)",
             "Primary Mediastinal (Thymic) Large B-Cell Lymphoma"),
            ("MDS with Isolated Del(5q) (MDS5Q)", "MDS with Isolated Del(5q)"),
        ):
            self.assertEqual(_parse_level_value(raw), expected)

    def test_read_oncotree_rows(self):
        rows, level_columns = _read_oncotree_rows()
        self.assertGreater(len(rows), 0)
        self.assertEqual(level_columns[0], "level_1")
        self.assertEqual(len(level_columns), 6)

    def test_get_all_oncotree_data(self):
        level_1_list, mapping_l1_all = get_all_oncotree_data()
        self.assertIn("Breast", level_1_list)        
        self.assertGreater(len(mapping_l1_all["Breast"]), 0)

        self.assertIn("APL with PML-RARA", mapping_l1_all["Myeloid"])

    def test_get_l1_l2_oncotree_data(self):
        level_1_list, mapping_l1_l2 = get_l1_l2_oncotree_data()
        pprint(sorted(level_1_list))
        pprint({k: sorted(v) for k, v in mapping_l1_l2.items()})
        self.assertIn("Breast", level_1_list)
        self.assertGreater(len(mapping_l1_l2["Breast"]), 0)
        self.assertIn("Diffuse Glioma", mapping_l1_l2["CNS/Brain"])


class TestOfferedNames(unittest.TestCase):
    """
    Every diagnosis the two mapping stages put in front of the model must be
    one the validator will accept back. When it is not, the model answers
    correctly and has the answer discarded - which is how five B-ALL and three
    AML cytogenetic subtypes were unreachable while looking like model error.
    """

    @staticmethod
    def _offered():
        level_1, l1_to_all = ot.get_all_oncotree_data()
        names = set(level_1)
        for children in l1_to_all.values():
            names |= children
        return names

    def test_every_offered_name_is_valid(self):
        rejected = sorted(n for n in self._offered()
                          if rv.canonical_diagnosis(n) is None)
        self.assertEqual(rejected, [])

    def test_level_1_categories_are_unchanged(self):
        level_1, _ = ot.get_all_oncotree_data()
        self.assertEqual(len(level_1), 32)

    def test_the_five_b_all_subtypes_stay_distinct(self):
        subtypes = {n for n in self._offered()
                    if n.startswith("B-Lymphoblastic Leukemia/Lymphoma with t(")}
        self.assertEqual(len(subtypes), 5, sorted(subtypes))

    def test_haematological_subtypes_are_reachable(self):
        names = self._offered()
        for node in (
            "B-Lymphoblastic Leukemia/Lymphoma with t(9;22)(q34.1;q11.2);BCR-ABL1",
            "B-Lymphoblastic Leukemia/Lymphoma with t(12;21)(p13.2;q22.1); ETV6-RUNX1",
            "B-Lymphoblastic Leukemia/Lymphoma with t(1;19)(q23;p13.3);TCF3-PBX1",
            "B-Lymphoblastic Leukemia/Lymphoma with t(v;11q23.3);KMT2A Rearranged",
            "AML with t(8;21)(q22;q22.1);RUNX1-RUNX1T1",
            "AML with inv(16)(p13.1q22) or t(16;16)(p13.1;q22);CBFB-MYH11",
            "Primary Mediastinal (Thymic) Large B-Cell Lymphoma",
        ):
            self.assertIn(node, names)


if __name__ == "__main__":
    unittest.main()
