import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from loguru import logger

import config
import utils.two_readers as tr
from src.trial_map_manager import TrialMapManager
from utils.build_trial_index import _population_reference
from utils.oncotree import get_lineage

logger.remove()


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _doc(diagnoses=(), genes=(), ages=()):
    """A one-step CTML with the given diagnoses, genomic nodes and age bounds."""
    clinical = [{"clinical": {"oncotree_primary_diagnosis": list(diagnoses)}}] if diagnoses else []
    clinical += [{"clinical": {"age_numerical": a}} for a in ages]
    genomic = [{"genomic": {"hugo_symbol": s, "variant_category": c}} for s, c in genes]
    return {
        "nct_id": "NCT0",
        "treatment_list": {"step": [{"match": [{"and": clinical + genomic}]}]},
    }


def _family():
    """
    An Oncotree parent with at least two leaf children, read from the tree in
    use rather than hard-coded, so a reference update cannot silently turn
    these tests into comparisons of unrelated names.
    """
    parent, level_1, descendants = get_lineage()
    _, codable, _, _ = _population_reference()
    for p in sorted(descendants):
        kids = sorted(
            k for k, v in parent.items() if v == p and k in codable and len(descendants[k]) == 1
        )
        if p in codable and p not in level_1 and len(kids) >= 2:
            return p, kids[0], kids[1]
    raise AssertionError("no parent with two leaf children in the Oncotree file")


class TestCompare(unittest.TestCase):
    """What counts as the two readers disagreeing, and in which direction."""

    @classmethod
    def setUpClass(cls):
        cls.parent, cls.child, cls.other = _family()

    def test_a_mapping_agrees_with_itself(self):
        doc = _doc([self.parent], [("MYCN", "Copy Number Variation")], [">=1", "<22"])
        self.assertTrue(tr.compare("NCT0", doc, doc).agree)

    def test_a_parent_and_its_children_reach_the_same_patients(self):
        # Wording differs, population does not: no disagreement. The parent is
        # itself codable, so the children alone reach all but that one code.
        _, codable, _, _ = _population_reference()
        _, _, descendants = get_lineage()
        kids = sorted(descendants[self.parent] - {self.parent})
        result = tr.compare("NCT0", _doc([self.parent]), _doc([self.parent] + kids))
        self.assertTrue(result.agree, [str(d) for d in result.differences])

    def test_a_population_only_the_second_reaches_narrows(self):
        result = tr.compare("NCT0", _doc([self.child]), _doc([self.child, self.other]))
        self.assertEqual([d.direction for d in result.differences], [tr.NARROWS])
        self.assertIn(self.other, result.differences[0].detail)
        self.assertTrue(result.narrows)

    def test_a_population_only_the_primary_reaches_widens(self):
        result = tr.compare("NCT0", _doc([self.parent]), _doc([self.child]))
        self.assertEqual([d.direction for d in result.differences], [tr.WIDENS])
        self.assertFalse(result.narrows)

    def test_an_exclusion_only_the_primary_has_narrows(self):
        result = tr.compare("NCT0", _doc([self.parent, "!" + self.child]), _doc([self.parent]))
        self.assertEqual([d.direction for d in result.differences], [tr.NARROWS])

    def test_a_wildcard_against_one_of_its_members_widens(self):
        result = tr.compare("NCT0", _doc(["_SOLID_"]), _doc(["Neuroblastoma"]))
        self.assertEqual(
            [(d.dimension, d.direction) for d in result.differences], [("diagnosis", tr.WIDENS)]
        )

    def test_a_gene_only_the_primary_requires_narrows(self):
        result = tr.compare(
            "NCT0",
            _doc([self.child], [("MYCN", "Copy Number Variation")]),
            _doc([self.child]),
        )
        self.assertEqual(
            [(d.dimension, d.direction) for d in result.differences], [("gene", tr.NARROWS)]
        )

    def test_a_gene_only_the_second_requires_widens(self):
        result = tr.compare("NCT0", _doc([self.child]), _doc([self.child], [("BRAF", "Mutation")]))
        self.assertEqual(
            [(d.dimension, d.direction) for d in result.differences], [("gene", tr.WIDENS)]
        )

    def test_required_and_excluded_are_different_genes(self):
        result = tr.compare(
            "NCT0",
            _doc([self.child], [("BCR", "Structural Variation")]),
            _doc([self.child], [("BCR", "!Structural Variation")]),
        )
        self.assertEqual(
            sorted(d.direction for d in result.differences), sorted([tr.NARROWS, tr.WIDENS])
        )

    def test_a_tighter_age_bound_narrows_and_a_looser_one_widens(self):
        tighter = tr.compare(
            "NCT0", _doc([self.child], ages=["<18"]), _doc([self.child], ages=["<22"])
        )
        self.assertEqual([d.direction for d in tighter.differences], [tr.NARROWS])
        looser = tr.compare("NCT0", _doc([self.child]), _doc([self.child], ages=["<22"]))
        self.assertEqual([d.direction for d in looser.differences], [tr.WIDENS])

    def test_less_than_and_at_most_are_the_same_bound(self):
        # MatchMiner maps < and <= to the same operator (bench.benchmark_map._age_key).
        result = tr.compare(
            "NCT0", _doc([self.child], ages=["<22"]), _doc([self.child], ages=["<=22"])
        )
        self.assertTrue(result.agree)


class TestReconcile(unittest.TestCase):
    """Flagging and routing: dry run by default, never a curated file."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.mapped = os.path.join(self.root, "cache", "ctml")
        self.review = os.path.join(self.root, "ctml", "needs-review")
        self.reviewed = os.path.join(self.root, "ctml", "reviewed")
        self.second = os.path.join(self.root, "second")
        for d in (self.mapped, self.review, self.reviewed, self.second):
            os.makedirs(d)
        self.parent, self.child, self.other = _family()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _put(self, directory, trial_id, doc, header=""):
        path = os.path.join(directory, f"{trial_id}.yaml")
        with open(path, "w") as handle:
            handle.write(header + yaml.safe_dump(doc, sort_keys=False))
        return path

    def _run(self, apply=False, route="any"):
        return {
            r["trial_id"]: r
            for r in tr.reconcile(
                self.mapped, self.second, self.review, self.reviewed, route, apply
            )
        }

    def test_a_dry_run_writes_nothing(self):
        self._put(self.mapped, "NCT1", _doc([self.child]))
        self._put(self.second, "NCT1", _doc([self.child, self.other]))
        rows = self._run()
        self.assertEqual(rows["NCT1"]["status"], "narrows")
        self.assertTrue(os.path.exists(os.path.join(self.mapped, "NCT1.yaml")))
        self.assertEqual(os.listdir(self.review), [])

    def test_apply_flags_and_moves_and_keeps_the_text(self):
        self._put(self.mapped, "NCT1", _doc([self.child]), header="# kept as written\n")
        self._put(self.second, "NCT1", _doc([self.child, self.other]))
        self._run(apply=True)
        self.assertFalse(os.path.exists(os.path.join(self.mapped, "NCT1.yaml")))
        moved = _text(os.path.join(self.review, "NCT1.yaml"))
        self.assertTrue(moved.startswith("# kept as written\n"))
        flag = yaml.safe_load(moved)[tr.FLAG]
        self.assertIn("diagnosis narrows", flag)
        self.assertEqual(
            TrialMapManager._destination_for(yaml.safe_load(moved), self.mapped, "NCT1"),
            config.CTML_REVIEW_PATH,
        )

    def test_agreeing_trials_are_left_alone(self):
        path = self._put(self.mapped, "NCT1", _doc([self.child]))
        before = _text(path)
        self._put(self.second, "NCT1", _doc([self.child]))
        self.assertEqual(self._run(apply=True)["NCT1"]["status"], "agree")
        self.assertEqual(_text(path), before)

    def test_a_curated_trial_is_never_compared(self):
        self._put(self.mapped, "NCT1", _doc([self.child]))
        self._put(self.reviewed, "NCT1", _doc([self.child]))
        self._put(self.second, "NCT1", _doc([self.other]))
        rows = self._run(apply=True)
        self.assertEqual(rows["NCT1"]["status"], "second only")
        self.assertTrue(os.path.exists(os.path.join(self.mapped, "NCT1.yaml")))

    def test_the_review_copy_is_the_one_compared_and_flagged(self):
        self._put(self.mapped, "NCT1", _doc([self.child, self.other]))
        self._put(self.review, "NCT1", _doc([self.child]))
        self._put(self.second, "NCT1", _doc([self.child, self.other]))
        rows = self._run(apply=True)
        self.assertEqual(rows["NCT1"]["status"], "narrows")
        self.assertIn(tr.FLAG, yaml.safe_load(_text(os.path.join(self.review, "NCT1.yaml"))))
        # The stale mapped copy is not touched.
        self.assertNotIn(tr.FLAG, yaml.safe_load(_text(os.path.join(self.mapped, "NCT1.yaml"))))

    def test_a_second_pass_replaces_the_flag_rather_than_stacking_it(self):
        self._put(self.mapped, "NCT1", _doc([self.child]))
        self._put(self.second, "NCT1", _doc([self.child, self.other]))
        self._run(apply=True)
        self._run(apply=True)
        raw = _text(os.path.join(self.review, "NCT1.yaml"))
        self.assertEqual(raw.count(f"{tr.FLAG}:"), 1)

    def test_narrows_routing_leaves_a_widening_trial_published(self):
        self._put(self.mapped, "NCT1", _doc([self.parent]))
        self._put(self.second, "NCT1", _doc([self.child]))
        rows = self._run(apply=True, route="narrows")
        self.assertEqual(rows["NCT1"]["status"], "widens")
        self.assertFalse(rows["NCT1"]["routed"])
        self.assertTrue(os.path.exists(os.path.join(self.mapped, "NCT1.yaml")))

    def test_the_flag_is_one_the_review_gate_knows(self):
        import utils.review.common as common

        self.assertIn(tr.FLAG, common.FLAG_KEYS)
        self.assertIn(tr.FLAG, common.ADVICE)


class TestMapOutKeepsReviewCopies(unittest.TestCase):
    """
    `map --out DIR` puts review-routed trials in DIR/needs-review. Until
    2026-10-20 they went to the curators' ctml/needs-review whatever --out
    said, so a second reader's run would have written into the review queue.
    """

    def _review_path_during(self, argv):
        import main as cli

        seen = {}
        original = config.CTML_REVIEW_PATH

        def fake_map(trial_id, src, out):
            seen[trial_id] = config.CTML_REVIEW_PATH

        out = tempfile.mkdtemp()
        try:
            with (
                mock.patch.object(sys, "argv", ["main.py", "map", *argv, "--out", out]),
                mock.patch.object(cli, "map_nct", fake_map),
                mock.patch.object(cli, "map_ctis", fake_map),
                mock.patch("utils.provenance.start_run"),
                mock.patch("utils.provenance.finish_run"),
            ):
                cli.main()
        finally:
            config.CTML_REVIEW_PATH = original
            shutil.rmtree(out)
        return seen, out

    def test_out_moves_the_review_path_inside_it(self):
        seen, out = self._review_path_during(["--nct_id", "NCT1"])
        self.assertEqual(seen["NCT1"], os.path.join(out, "needs-review"))

    def test_ids_maps_each_registry_in_one_run(self):
        seen, out = self._review_path_during(["--ids", "NCT1, 2024-511989-36-00,NCT1"])
        self.assertEqual(sorted(seen), ["2024-511989-36-00", "NCT1"])

    def test_ids_reads_a_file(self):
        import main as cli

        handle, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(handle, "w") as f:
            f.write("NCT1\n# a comment\n\nNCT2  # trailing\n")
        try:
            self.assertEqual(cli._read_ids("@" + path), ["NCT1", "NCT2"])
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
