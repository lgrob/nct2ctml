"""
Decision D6: a stale needs-review copy is kept, still published, and the
conflict with a newer clean mapping is reported - never resolved silently.
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
from src.trial_map_manager import TrialMapManager
from utils import build_trial_index as bti

logger.remove()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRIAL = "NCT03643276"
SRC = os.path.join(ROOT, "ctml", "reviewed", f"{TRIAL}.yaml")


def _layers(tmp, mapped_age, review_age, reviewed=False):
    """Copies of one real trial in each layer, with mtimes `age` seconds ago."""
    dirs = {name: os.path.join(tmp, name) for name in ("mapped", "needs_review", "reviewed")}
    for d in dirs.values():
        os.makedirs(d)
    now = 2_000_000_000
    for name, age in (("mapped", mapped_age), ("needs_review", review_age)):
        path = os.path.join(dirs[name], f"{TRIAL}.yaml")
        shutil.copy(SRC, path)
        os.utime(path, (now - age, now - age))
    if reviewed:
        shutil.copy(SRC, os.path.join(dirs["reviewed"], f"{TRIAL}.yaml"))
    return [(dirs["mapped"], "mapped"), (dirs["needs_review"], "needs_review"), (dirs["reviewed"], "reviewed")]


def _build(layers):
    out = tempfile.mkdtemp()
    manifest = bti.build(layers, out)
    trials = list(csv.DictReader(open(os.path.join(out, "trials.tsv")), delimiter="\t"))
    conflicts = list(csv.DictReader(open(os.path.join(out, "layer_conflicts.tsv")), delimiter="\t"))
    return manifest, trials, conflicts


@unittest.skipUnless(os.path.exists(SRC), "reviewed trial not present")
class TestLayerConflicts(unittest.TestCase):

    def test_a_newer_clean_mapping_is_reported_and_the_review_copy_still_wins(self):
        manifest, trials, conflicts = _build(_layers(tempfile.mkdtemp(), mapped_age=10, review_age=1000))
        self.assertEqual(trials[0]["review_status"], "needs_review")
        self.assertEqual(trials[0]["layer_conflict"], "newer_mapped_copy")
        self.assertEqual([(c["trial_id"], c["published_status"], c["newer_status"]) for c in conflicts],
                         [(TRIAL, "needs_review", "mapped")])
        self.assertEqual(manifest["layer_conflicts"], 1)
        self.assertIn("layer_conflicts.tsv", manifest["outputs"])

    def test_an_older_mapped_copy_under_review_is_the_normal_case(self):
        manifest, trials, conflicts = _build(_layers(tempfile.mkdtemp(), mapped_age=1000, review_age=10))
        self.assertEqual((trials[0]["review_status"], trials[0]["layer_conflict"]), ("needs_review", ""))
        self.assertEqual((conflicts, manifest["layer_conflicts"]), ([], 0))

    def test_a_reviewed_copy_over_newer_machine_output_is_not_a_conflict(self):
        _, trials, conflicts = _build(_layers(tempfile.mkdtemp(), mapped_age=10, review_age=1000, reviewed=True))
        self.assertEqual((trials[0]["review_status"], trials[0]["layer_conflict"], conflicts), ("reviewed", "", []))


class TestMapperWarns(unittest.TestCase):

    def test_a_clean_mapping_leaves_the_review_copy_in_place(self):
        review = tempfile.mkdtemp()
        stale = os.path.join(review, "NCT1.yaml")
        open(stale, "w").write("old: copy\n")
        doc = {"treatment_list": {"step": [{"match": [{"clinical": {"oncotree_primary_diagnosis": "Melanoma"}}]}]}}
        seen = []
        handler = logger.add(lambda m: seen.append(str(m)), level="WARNING")
        try:
            with mock.patch.object(config, "CTML_REVIEW_PATH", review):
                self.assertEqual(TrialMapManager._destination_for(doc, "cache/ctml", "NCT1"), "cache/ctml")
        finally:
            logger.remove(handler)
        self.assertEqual(open(stale).read(), "old: copy\n")
        self.assertTrue(any("layer_conflicts.tsv" in m for m in seen))


class TestReviewCopyBackups(unittest.TestCase):
    """A re-run that sends a trial to review again keeps the old review copy."""

    def setUp(self):
        self.review = tempfile.mkdtemp()
        self.patch = mock.patch.object(config, "CTML_REVIEW_PATH", self.review)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _files(self):
        return sorted(os.listdir(self.review))

    def test_a_differing_review_copy_is_kept_as_prev(self):
        open(os.path.join(self.review, "NCT1.yaml"), "w").write("curator: edits\n")
        TrialMapManager._save({"nct_id": "NCT1"}, self.review, "NCT1")
        self.assertEqual(self._files(), ["NCT1.yaml", "NCT1.yaml.prev"])
        self.assertEqual(open(os.path.join(self.review, "NCT1.yaml.prev")).read(), "curator: edits\n")

    def test_backups_are_never_overwritten(self):
        open(os.path.join(self.review, "NCT1.yaml"), "w").write("first\n")
        TrialMapManager._save({"v": 2}, self.review, "NCT1")
        TrialMapManager._save({"v": 3}, self.review, "NCT1")
        self.assertEqual(self._files(), ["NCT1.yaml", "NCT1.yaml.prev", "NCT1.yaml.prev.1"])
        self.assertEqual(open(os.path.join(self.review, "NCT1.yaml.prev")).read(), "first\n")

    def test_an_identical_copy_gets_no_backup(self):
        TrialMapManager._save({"v": 1}, self.review, "NCT1")
        TrialMapManager._save({"v": 1}, self.review, "NCT1")
        self.assertEqual(self._files(), ["NCT1.yaml"])

    def test_the_mapped_output_is_overwritten_without_backup(self):
        mapped = tempfile.mkdtemp()
        open(os.path.join(mapped, "NCT1.yaml"), "w").write("old\n")
        TrialMapManager._save({"v": 2}, mapped, "NCT1")
        self.assertEqual(sorted(os.listdir(mapped)), ["NCT1.yaml"])

    @unittest.skipUnless(os.path.exists(SRC), "reviewed trial not present")
    def test_the_index_ignores_backups_and_lists_them(self):
        shutil.copy(SRC, os.path.join(self.review, f"{TRIAL}.yaml"))
        shutil.copy(SRC, os.path.join(self.review, f"{TRIAL}.yaml.prev"))
        manifest, trials, _ = _build([(tempfile.mkdtemp(), "mapped"), (self.review, "needs_review")])
        self.assertEqual([t["trial_id"] for t in trials], [TRIAL])
        self.assertEqual(manifest["review_backups"], [os.path.join(self.review, f"{TRIAL}.yaml.prev")])


if __name__ == "__main__":
    unittest.main()
