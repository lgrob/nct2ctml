"""
bench/benchmark_map.py over both registries (roadmap step 1.5).

The curated key holds 50 ClinicalTrials.gov and 5 CTIS trials; until this
step only the NCT ones were read. These tests run on the real key and the
real cache. Nothing is mapped by a model: full mapping is exercised with
TrialMapManager patched, as tests/test_main_cli.py does for main.py.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from loguru import logger

import bench.benchmark_map as bm
import src.clinical_trials_gov as ctg

logger.remove()

CTIS_ID = "2023-505575-69-01"   # conditions: ["Osteosarcoma"]
NCT_ID = "NCT07440290"


def _have_cache():
    return (os.path.isdir(os.path.join(ROOT, bm.CACHE_DIRS["ctis"]))
            and os.path.isdir(os.path.join(ROOT, bm.CACHE_DIRS["nct"])))


def _run_main(*argv):
    """bench.benchmark_map.main() from the repo root; returns the JSON rows."""
    out_json = os.path.join(tempfile.mkdtemp(), "report.json")
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        with patch.object(sys, "argv", ["benchmark_map", *argv, "--json", out_json]), \
             contextlib.redirect_stdout(io.StringIO()):
            bm.main()
    finally:
        os.chdir(cwd)
        logger.remove()
    with open(out_json) as handle:
        return json.load(handle)


class TestRegistryOf(unittest.TestCase):

    def test_nct_ctis_and_neither(self):
        self.assertEqual(bm.registry_of("NCT04320888"), "nct")
        self.assertEqual(bm.registry_of("2025-520982-39-00"), "ctis")
        self.assertIsNone(bm.registry_of("README"))
        self.assertIsNone(bm.registry_of("2025-520982-39"))


class TestTrialIds(unittest.TestCase):

    def test_curated_key_holds_both_registries_nct_first(self):
        ids = bm.trial_ids(os.path.join(ROOT, bm.TRUTH_DIR))
        regs = [bm.registry_of(t) for t in ids]
        self.assertEqual((len(ids), regs.count("nct"), regs.count("ctis")), (55, 50, 5))
        # --limit N keeps meaning "the first N NCT trials".
        self.assertEqual(regs, sorted(regs, key=bm.REGISTRIES.index))

    def test_source_restricts_to_one_registry(self):
        truth = os.path.join(ROOT, bm.TRUTH_DIR)
        self.assertEqual({bm.registry_of(t) for t in bm.trial_ids(truth, "ctis")}, {"ctis"})
        self.assertEqual(len(bm.trial_ids(truth, "nct")), 50)


@unittest.skipUnless(_have_cache(), "registry cache not present")
class TestConditionsOnly(unittest.TestCase):

    def test_ctis_conditions_come_from_the_ctis_accessor(self):
        with open(os.path.join(ROOT, bm.CACHE_DIRS["ctis"], CTIS_ID + ".json")) as handle:
            record = json.load(handle)
        self.assertEqual(bm.conditions_of(CTIS_ID, record), ["Osteosarcoma"])

    def test_ctis_goes_through_the_shared_seed_without_eligibility_text(self):
        out = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            with patch.object(ctg, "seed_and_map_diagnosis",
                              wraps=ctg.seed_and_map_diagnosis) as seed:
                bm.write_conditions_baseline([CTIS_ID], out)
        finally:
            os.chdir(cwd)
            logger.remove()
        seed.assert_called_once_with(CTIS_ID, ["Osteosarcoma"], "")
        rows, _ = bm.score(os.path.join(ROOT, bm.TRUTH_DIR), out, [CTIS_ID])
        self.assertEqual(rows[0]["registry"], "ctis")
        self.assertEqual(rows[0]["dx_spurious"], [])
        self.assertEqual(rows[0]["pop_r"], 1.0)

    def test_conditions_only_scores_every_trial_of_both_registries(self):
        rows = _run_main("--conditions-only", "--out", tempfile.mkdtemp())
        self.assertEqual(len(rows), 55)
        self.assertTrue(all(r["status"] == "ok" for r in rows))
        self.assertEqual(sum(r["registry"] == "ctis" for r in rows), 5)


class TestScoreOnlyIdentity(unittest.TestCase):

    def test_key_scored_against_itself_is_perfect_in_both_registries(self):
        rows = _run_main("--score-only", "--out", bm.TRUTH_DIR)
        self.assertEqual(len(rows), 55)
        means = bm.registry_means(rows)
        self.assertEqual((means["nct"]["n"], means["ctis"]["n"]), (50, 5))
        for name in ("all", "nct", "ctis"):
            for key in ("dx_f1", "pop_f1", "gene_f1", "age_f1"):
                self.assertEqual(means[name][key], 1.0, (name, key))

    def test_registry_absent_from_the_run_is_absent_from_the_means(self):
        rows = _run_main("--score-only", "--out", bm.TRUTH_DIR, "--source", "ctis")
        self.assertEqual(set(bm.registry_means(rows)), {"all", "ctis"})


class TestFullMappingDispatch(unittest.TestCase):

    def test_each_registry_goes_to_its_own_mapper(self):
        mgr = MagicMock()
        bm.map_trial(mgr, CTIS_ID, "out")
        mgr.map_single_ctis_trial.assert_called_once_with(CTIS_ID, bm.CACHE_DIRS["ctis"], "out")
        mgr.map_single_trial.assert_not_called()
        bm.map_trial(mgr, NCT_ID, "out")
        mgr.map_single_trial.assert_called_once_with(NCT_ID, bm.CACHE_DIRS["nct"], "out")

    def test_main_maps_ctis_trials_with_the_ctis_mapper(self):
        out = tempfile.mkdtemp()
        truth = os.path.join(ROOT, bm.TRUTH_DIR)

        def fake_map(trial_id, cache_dir, out_dir):
            # Stand in for the model: write the curated answer.
            shutil.copy(os.path.join(truth, trial_id + ".yaml"), out_dir)
            return True

        mgr = MagicMock()
        mgr.map_single_ctis_trial.side_effect = fake_map
        with patch("src.trial_map_manager.TrialMapManager", return_value=mgr):
            rows = _run_main("--source", "ctis", "--out", out)
        self.assertEqual(mgr.map_single_ctis_trial.call_count, 5)
        mgr.map_single_trial.assert_not_called()
        self.assertEqual([r["registry"] for r in rows], ["ctis"] * 5)
        self.assertTrue(all(r["dx_f1"] == 1.0 for r in rows))


class TestUnsatisfiable(unittest.TestCase):

    def test_present_and_absent_in_separate_alternatives_is_satisfiable(self):
        from bench.benchmark_map import unsatisfiable
        g = lambda vc: {"genomic": {"hugo_symbol": "EWSR1", "variant_category": vc}}
        tree = {"and": [{"clinical": {"age_numerical": ">=1"}},
                        {"or": [{"and": [g("Structural Variation")]}, {"and": [g("!Structural Variation")]}]}]}
        self.assertEqual(unsatisfiable([tree]), set())

    def test_present_and_absent_in_one_and_is_flagged(self):
        from bench.benchmark_map import unsatisfiable
        tree = {"and": [{"genomic": {"hugo_symbol": "BRAF", "variant_category": "Mutation"}},
                        {"genomic": {"hugo_symbol": "BRAF", "variant_category": "!Mutation"}}]}
        self.assertEqual(unsatisfiable([tree]), {"BRAF"})


if __name__ == "__main__":
    unittest.main()
