"""
The flat index must never widen or invent what the curated CTML says.

It is a screening view: every row is something the trial could match, and the
CTML file remains the authority on whether it does. These tests pin the two
properties a consumer relies on - that an emitted code is always a real
Oncotree node, and that expansion only ever adds descendants of what the
curator wrote.
"""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

from utils.build_trial_index import (
    LIQUID_ROOTS,
    _basket_members,
    _name_to_code,
    _parse_age_bounds,
    build,
    index_trial,
)
from utils.oncotree import get_all_oncotree_data, get_lineage
from utils.reference_validation import _oncotree

logger.remove()

REVIEWED = os.path.join(os.path.dirname(__file__), '..', 'ctml', 'reviewed')


def _trial(match, **fields):
    return {"treatment_list": {"step": [{"match": [match]}]}, **fields}


def _index(trial, trial_id="T1"):
    _, _, descendants = get_lineage()
    solid, liquid = _basket_members()
    return index_trial(trial_id, trial, descendants, solid, liquid, _name_to_code())


class TestDiagnosisExpansion(unittest.TestCase):
    def test_a_parent_expands_to_its_descendants(self):
        _, diagnoses, _ = _index(
            _trial({"clinical": {"oncotree_primary_diagnosis": "Rhabdomyosarcoma"}}))
        names = {row["oncotree_name"] for row in diagnoses}
        self.assertIn("Rhabdomyosarcoma", names)
        self.assertIn("Alveolar Rhabdomyosarcoma", names)
        self.assertIn("Embryonal Rhabdomyosarcoma", names)

    def test_expansion_only_ever_adds_descendants(self):
        """
        The property a consumer depends on: a screening hit always traces back
        to something at or below the term the curator wrote.
        """
        _, _, descendants = get_lineage()
        solid, liquid = _basket_members()
        for filename in sorted(os.listdir(REVIEWED)):
            if not filename.endswith('.yaml'):
                continue
            import yaml
            trial = yaml.safe_load(open(os.path.join(REVIEWED, filename)))
            _, diagnoses, _ = _index(trial, filename[:-5])
            for row in diagnoses:
                if row["from_basket"]:
                    continue
                self.assertIn(row["oncotree_name"],
                              descendants.get(row["source_term"], set()),
                              f"{filename}: {row['oncotree_name']} is not under "
                              f"{row['source_term']}")

    def test_every_emitted_name_is_a_real_oncotree_node(self):
        names, _, _ = _oncotree()
        manifest_dir = tempfile.mkdtemp()
        build(REVIEWED, manifest_dir)
        with open(os.path.join(manifest_dir, 'trial_diagnosis.tsv')) as handle:
            for row in csv.DictReader(handle, delimiter='\t'):
                self.assertIn(row["oncotree_name"], names)

    def test_a_leaf_emits_exactly_itself(self):
        _, diagnoses, _ = _index(
            _trial({"clinical": {"oncotree_primary_diagnosis": "Neuroblastoma"}}))
        self.assertEqual([row["oncotree_name"] for row in diagnoses], ["Neuroblastoma"])

    def test_the_code_column_is_populated(self):
        """Codes outlive display names; a consumer should be able to join on them."""
        _, diagnoses, _ = _index(
            _trial({"clinical": {"oncotree_primary_diagnosis": "Neuroblastoma"}}))
        self.assertEqual(diagnoses[0]["oncotree_code"], "NBL")


class TestBaskets(unittest.TestCase):
    def test_solid_and_liquid_partition_the_tree(self):
        solid, liquid = _basket_members()
        level_1, level_1_to_all = get_all_oncotree_data()
        everything = {n for root in level_1 for n in level_1_to_all[root] | {root}}
        self.assertEqual(solid | liquid, everything)
        self.assertEqual(solid & liquid, set())

    def test_a_liquid_basket_does_not_reach_solid_tumours(self):
        _, diagnoses, _ = _index(
            _trial({"clinical": {"oncotree_primary_diagnosis": "_LIQUID_"}}))
        names = {row["oncotree_name"] for row in diagnoses}
        self.assertIn("B-Lymphoblastic Leukemia/Lymphoma", names)
        self.assertNotIn("Neuroblastoma", names)

    def test_a_solid_basket_does_not_reach_leukaemias(self):
        _, diagnoses, _ = _index(
            _trial({"clinical": {"oncotree_primary_diagnosis": "_SOLID_"}}))
        names = {row["oncotree_name"] for row in diagnoses}
        self.assertIn("Neuroblastoma", names)
        self.assertNotIn("B-Lymphoblastic Leukemia/Lymphoma", names)

    def test_basket_rows_are_flagged(self):
        _, diagnoses, _ = _index(
            _trial({"clinical": {"oncotree_primary_diagnosis": "_SOLID_"}}))
        self.assertTrue(all(row["from_basket"] == 1 for row in diagnoses))

    def test_liquid_roots_are_real_level_1_nodes(self):
        level_1, _ = get_all_oncotree_data()
        for root in LIQUID_ROOTS:
            self.assertIn(root, level_1)


class TestAgeBounds(unittest.TestCase):
    def test_a_two_sided_window(self):
        self.assertEqual(_parse_age_bounds([">=1", "<=21"]), (1.0, True, 21.0, True))

    def test_exclusive_bounds_are_kept_distinct(self):
        # "<18" and "<=18" differ by a whole year of patients.
        self.assertEqual(_parse_age_bounds(["<18"]), (None, None, 18.0, False))
        self.assertEqual(_parse_age_bounds(["<=18"]), (None, None, 18.0, True))

    def test_several_bounds_combine_to_the_most_restrictive(self):
        # Sibling clinical nodes under `and` are intersected by the engine.
        self.assertEqual(_parse_age_bounds([">=1", ">=2", "<=30", "<=21"]),
                         (2.0, True, 21.0, True))

    def test_fractional_ages_survive(self):
        self.assertEqual(_parse_age_bounds([">=0.08"]), (0.08, True, None, None))

    def test_unparseable_bounds_are_ignored_not_guessed(self):
        self.assertEqual(_parse_age_bounds(["Children", ""]), (None, None, None, None))


class TestGenomicRows(unittest.TestCase):
    def test_an_exclusion_is_flagged_not_dropped(self):
        _, _, genomics = _index(_trial(
            {"genomic": {"hugo_symbol": "ABL1", "variant_category": "!Any Variation"}}))
        self.assertEqual(genomics[0]["include"], 0)
        self.assertEqual(genomics[0]["variant_category"], "Any Variation")

    def test_an_inclusion_is_marked_included(self):
        _, _, genomics = _index(_trial(
            {"genomic": {"hugo_symbol": "MYCN", "variant_category": "Amplification"}}))
        self.assertEqual(genomics[0]["include"], 1)


class TestArmScope(unittest.TestCase):
    def test_an_arm_specific_match_is_attributed_to_its_arm(self):
        trial = {"treatment_list": {"step": [{
            "match": [{"clinical": {"oncotree_primary_diagnosis": "Neuroblastoma"}}],
            "arm": [{"arm_code": "ARM_A", "match": [
                {"clinical": {"oncotree_primary_diagnosis": "Ewing Sarcoma"}}]}],
        }]}}
        _, diagnoses, _ = _index(trial)
        by_arm = {row["oncotree_name"]: row["arm_code"] for row in diagnoses}
        self.assertEqual(by_arm["Neuroblastoma"], "")
        self.assertEqual(by_arm["Ewing Sarcoma"], "ARM_A")


class TestBuildOutputs(unittest.TestCase):
    def test_the_build_is_deterministic(self):
        """
        Byte-identical outputs from identical inputs. This is what lets a
        manifest checksum identify the trial set behind a report.
        """
        first, second = tempfile.mkdtemp(), tempfile.mkdtemp()
        a, b = build(REVIEWED, first), build(REVIEWED, second)
        for name in ("trials.tsv", "trial_diagnosis.tsv", "trial_genomic.tsv"):
            self.assertEqual(a["outputs"][name]["sha256"], b["outputs"][name]["sha256"],
                             name)

    def test_the_manifest_records_the_vocabulary_it_was_built_against(self):
        out = tempfile.mkdtemp()
        manifest = build(REVIEWED, out)
        self.assertEqual(len(manifest["oncotree_sha256"]), 64)
        self.assertTrue(os.path.exists(os.path.join(out, "manifest.json")))
        with open(os.path.join(out, "manifest.json")) as handle:
            self.assertEqual(json.load(handle)["trials"], manifest["trials"])

    def test_every_diagnosis_row_points_at_an_indexed_trial(self):
        out = tempfile.mkdtemp()
        build(REVIEWED, out)
        with open(os.path.join(out, "trials.tsv")) as handle:
            known = {row["trial_id"] for row in csv.DictReader(handle, delimiter='\t')}
        with open(os.path.join(out, "trial_diagnosis.tsv")) as handle:
            for row in csv.DictReader(handle, delimiter='\t'):
                self.assertIn(row["trial_id"], known)


if __name__ == '__main__':
    unittest.main()
