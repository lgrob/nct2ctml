"""
scripts/merge_upstream.py: for a conflicted upstream file it names, per
function upstream changed, where that function lives in this fork now.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts import merge_upstream as mu

BASE = "def kept():\n    return 1\n\n\ndef fixed():\n    return 2\n\n\ndef dropped():\n    pass\n"
TIP = "def kept():\n    return 1\n\n\ndef fixed():\n    return 3\n\n\ndef added():\n    pass\n"


class TestMovedHints(unittest.TestCase):
    def test_changed_added_and_removed_functions_are_found(self):
        self.assertEqual(mu.changed_functions(BASE, TIP), ["added", "dropped", "fixed"])

    def test_an_unchanged_or_unparseable_file_has_none(self):
        self.assertEqual(mu.changed_functions(BASE, BASE), [])
        self.assertEqual(mu.changed_functions("def (:", TIP), ["added", "fixed", "kept"])

    def test_a_function_is_located_in_this_fork(self):
        # map_ctml_match_genomic_criteria moved out of clinical_trials_gov in step 11.
        found = mu.where_now(["map_ctml_match_genomic_criteria", "no_such_function_here"])
        self.assertEqual(found["map_ctml_match_genomic_criteria"], ["src/mapping/genomic.py"])
        self.assertEqual(found["no_such_function_here"], [])

    def test_hints_name_only_what_moved(self):
        with (
            mock.patch.object(mu, "show", side_effect=[BASE.encode(), TIP.encode()]),
            mock.patch.object(mu, "where_now", return_value={
                "added": [], "dropped": ["src/x.py"], "fixed": ["src/mapping/y.py"],
            }),
        ):  # fmt: skip
            hints = mu.moved_hints("src/x.py", "base", "tip")
        self.assertEqual(
            hints,
            [
                "      upstream changed added(): now in nowhere here (removed, or renamed)",
                "      upstream changed fixed(): now in src/mapping/y.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
