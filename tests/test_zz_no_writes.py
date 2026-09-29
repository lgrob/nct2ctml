"""
Runs last (unittest discovers modules in name order): no test changed
anything under ctml/, cache/ctml, ref/, index/, runs/ or review_sheets/.
Tests that write use temporary directories (tests/support.temporary_layers).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests import support


class TestNoWrites(unittest.TestCase):
    def test_no_test_changed_the_protected_directories(self):
        if support.STATE_AT_START is None:
            self.skipTest("run as a package (-t .) so the start state is recorded")
        before, after = support.STATE_AT_START, support.protected_state()
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        self.assertEqual(changed, [], f"tests changed files they must not: {changed[:10]}")


if __name__ == "__main__":
    unittest.main()
