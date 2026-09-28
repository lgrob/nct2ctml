"""
Index releases (utils/release_index.py): only from a clean checkout, packed
reproducibly, tagged with the archive's hash, and verifiable down to a
byte-identical rebuild from the tagged commit.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils import release_index as ri

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DAY = datetime(2026, 10, 1, tzinfo=UTC)
# Tagging needs an identity, which CI runners do not have.
IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.org",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.org",
}


class TestUnits(unittest.TestCase):
    def test_versions_count_up_within_a_day(self):
        def tags(existing):
            return mock.patch.object(ri, "git", return_value="\n".join(existing))

        with tags([]):
            self.assertEqual(ri.next_version(DAY), "index-2026.10.01")
        with tags(["index-2026.10.01"]):
            self.assertEqual(ri.next_version(DAY), "index-2026.10.01.2")
        with tags(["index-2026.10.01", "index-2026.10.01.2"]):
            self.assertEqual(ri.next_version(DAY), "index-2026.10.01.3")

    def test_the_archive_depends_only_on_names_and_contents(self):
        a = ri.archive_bytes({"r/b.tsv": b"2\n", "r/a.tsv": b"1\n"})
        b = ri.archive_bytes({"r/a.tsv": b"1\n", "r/b.tsv": b"2\n"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, ri.archive_bytes({"r/a.tsv": b"1\n", "r/b.tsv": b"3\n"}))


@unittest.skipUnless(os.path.isdir(os.path.join(ROOT, ".git")), "not a git checkout")
class TestRelease(unittest.TestCase):
    """The whole cycle, in a throwaway clone of this repository's HEAD."""

    @classmethod
    def setUpClass(cls):
        cls.env = mock.patch.dict(os.environ, IDENTITY)
        cls.env.start()
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "repo")
        subprocess.run(["git", "clone", "--quiet", ROOT, cls.root], check=True)
        cls.version, cls.archive, cls.digest = ri.create(root=cls.root, today=DAY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)
        cls.env.stop()

    def test_a_release_is_tagged_with_its_archive_hash(self):
        self.assertEqual(self.version, "index-2026.10.01")
        message = ri.git("tag", "--list", "--format=%(contents)", self.version, root=self.root)
        self.assertIn(self.digest, message)
        with open(self.archive + ".sha256") as handle:
            self.assertEqual(handle.read().split()[0], self.digest)

    def test_release_json_says_what_it_was_built_from(self):
        members = ri._extract(self.archive)
        release = json.loads(members[f"{self.version}/release.json"])
        head = ri.git("rev-parse", "HEAD", root=self.root).strip()
        self.assertEqual(
            (release["commit"], release["source"], release["strict"]), (head, "ctml/reviewed", True)
        )
        self.assertEqual(sorted(release["outputs"]), sorted(ri.OUTPUTS))
        self.assertTrue(release["reviewed_ctml_sha256"])

    def test_it_verifies_and_rebuilds_byte_identical(self):
        _, _, problems = ri.verify(self.archive, rebuild=True, root=self.root)
        self.assertEqual(problems, [])

    def test_a_forged_archive_fails_on_the_tag(self):
        members = ri._extract(self.archive)
        name = f"{self.version}/trial_genomic.tsv"
        members[name] += b"NCT00000000\tforged\n"
        release = json.loads(members[f"{self.version}/release.json"])
        release["outputs"]["trial_genomic.tsv"]["sha256"] = hashlib.sha256(
            members[name]
        ).hexdigest()
        members[f"{self.version}/release.json"] = json.dumps(release).encode()
        forged = os.path.join(self.tmp, f"{self.version}.tar.gz")
        with open(forged, "wb") as handle:
            handle.write(ri.archive_bytes(members))
        _, _, problems = ri.verify(forged, root=self.root)
        self.assertEqual(
            problems, [f"archive does not match the SHA-256 recorded in tag {self.version}"]
        )

    def test_an_uncommitted_change_is_refused(self):
        path = os.path.join(self.root, "ctml", "reviewed", "NCT00000001.yaml")
        with open(path, "w") as handle:
            handle.write("nct_id: NCT00000001\n")
        try:
            problems = ri.preflight(self.root)
        finally:
            os.remove(path)
        self.assertTrue(
            any("not clean" in p and "NCT00000001.yaml" in p for p in problems), problems
        )


if __name__ == "__main__":
    unittest.main()
