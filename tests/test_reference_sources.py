"""
ref/SOURCES.tsv accounts for every reference file, and the pinned ones are
unchanged (utils/verify_refs.py). A file replaced without its fetch or build
step, or added without saying where it came from, fails here.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from utils import provenance
from utils import verify_refs as vr

PADDED = (
    "level_1\tlevel_2\tlevel_3\tlevel_4\tlevel_5\tlevel_6\tmetamaintype\tmetacolor\tmetanci\tmetaumls\thistory\n"
    "Testis (TESTIS)\t\t\t\t\t\tGerm Cell Tumor\tRed\tC1\tU1\t\n"
    "Testis (TESTIS)\tYolk Sac Tumor (YST)\t\t\t\t\tGerm Cell Tumor\tRed\tC2\tU2\t\n"
)
# The same export as the API serves it: empty levels left out.
RAGGED = (
    "level_1\tlevel_2\tlevel_3\tlevel_4\tlevel_5\tlevel_6\tmetamaintype\tmetacolor\tmetanci\tmetaumls\thistory\n"
    "Testis (TESTIS)\tGerm Cell Tumor\tRed\tC1\tU1\t\n"
    "Testis (TESTIS)\tYolk Sac Tumor (YST)\tGerm Cell Tumor\tRed\tC2\tU2\t\n"
)


class TestRepository(unittest.TestCase):
    def test_every_reference_file_is_accounted_for_and_unchanged(self):
        self.assertEqual(vr.check(), [])

    def test_every_file_the_mapper_hashes_is_listed(self):
        listed = vr.load_sources()
        self.assertEqual(set(provenance.reference_files()) - set(listed), set())

    def test_external_files_are_pinned_and_curated_ones_are_not(self):
        for path, row in vr.load_sources().items():
            if row["kind"] == "curated":
                self.assertEqual(row["sha256"], "", path)
            else:
                self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$", path)
                self.assertTrue(row["source"] and row["retrieved"], path)


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.sources = vr.load_sources()

    def test_a_changed_pinned_file_fails(self):
        panel = config.GENE_LIST_FILE_PATH
        self.sources[panel] = dict(self.sources[panel], sha256="0" * 64)
        (problem,) = vr.check(self.sources)
        self.assertIn(f"--update {panel}", problem)

    def test_an_unlisted_file_fails(self):
        del self.sources["ref/translocation_fusions.tsv"]
        self.assertEqual(
            vr.check(self.sources),
            [f"ref/translocation_fusions.tsv: in ref/ but not listed in {vr.SOURCES}"],
        )

    def test_a_missing_file_fails(self):
        self.sources["ref/gone.tsv"] = {"kind": "curated", "sha256": ""}
        self.assertEqual(
            vr.check(self.sources), [f"ref/gone.tsv: listed in {vr.SOURCES} but missing"]
        )

    def test_a_pinned_kind_without_a_hash_fails(self):
        panel = config.GENE_LIST_FILE_PATH
        self.sources[panel] = dict(self.sources[panel], sha256="")
        self.assertEqual(vr.check(self.sources), [f"{panel}: kind supplied but no sha256 pinned"])


class TestUpdate(unittest.TestCase):
    """--update re-pins in place, in a scratch copy of the layout without git."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "ref"))
        self.write("ref/panel.txt", "KRAS\n")
        self.write("ref/notes.tsv", "x\n")
        self.write(
            vr.SOURCES,
            "# comment kept\n"
            "file\tkind\tsource\tversion\tretrieved\tsha256\tnotes\n"
            f"ref/panel.txt\tsupplied\tsomeone\tv1\t2026-01-01\t{'0' * 64}\t\n"
            "ref/notes.tsv\tcurated\tthis repository\t\t\t\t\n",
        )
        patch = mock.patch.object(vr, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, path, text):
        with open(os.path.join(self.root, path), "w") as handle:
            handle.write(text)

    def test_update_pins_the_current_hash_and_date_and_keeps_comments(self):
        self.assertEqual(len(vr.check()), 1)
        vr.update(["ref/panel.txt"], today="2026-09-28")
        self.assertEqual(vr.check(), [])
        row = vr.load_sources()["ref/panel.txt"]
        self.assertEqual(
            (row["retrieved"], row["sha256"]), ("2026-09-28", vr.sha256("ref/panel.txt"))
        )
        with open(os.path.join(self.root, vr.SOURCES)) as handle:
            self.assertTrue(handle.read().startswith("# comment kept\n"))

    def test_a_curated_file_cannot_be_pinned(self):
        with self.assertRaises(SystemExit):
            vr.update(["ref/notes.tsv"])

    def test_without_git_the_files_on_disk_are_checked(self):
        self.write("ref/new.tsv", "y\n")
        self.assertIn(f"ref/new.tsv: in ref/ but not listed in {vr.SOURCES}", vr.check())


class TestOncotree(unittest.TestCase):
    def test_both_layouts_read_as_the_same_tree(self):
        self.assertEqual(vr.oncotree_rows(PADDED), vr.oncotree_rows(RAGGED))

    def test_padding_the_api_layout_gives_the_file_layout(self):
        self.assertEqual(vr.padded(RAGGED), PADDED)

    def test_metadata_differences_are_notes_not_tree_differences(self):
        tree, meta = vr.compare_oncotree(PADDED, RAGGED.replace("\tC2\t", "\tC2,C3\t"))
        self.assertEqual(tree, [])
        self.assertEqual(len(meta), 1)
        self.assertIn("Yolk Sac Tumor (YST)", meta[0])

    def test_a_node_added_or_removed_is_a_tree_difference(self):
        tree, _ = vr.compare_oncotree(
            PADDED, RAGGED.replace("Yolk Sac Tumor (YST)", "Seminoma (SEM)")
        )
        self.assertEqual(
            tree,
            [
                "only in ref/: Testis (TESTIS) > Yolk Sac Tumor (YST)",
                "only upstream: Testis (TESTIS) > Seminoma (SEM)",
            ],
        )

    def test_sources_names_the_oncotree_version_the_docs_name(self):
        version = vr.load_sources()[vr.ONCOTREE_FILE]["version"]
        with open(os.path.join(vr.ROOT, "README.md")) as handle:
            self.assertIn(version, handle.read())


if __name__ == "__main__":
    unittest.main()
