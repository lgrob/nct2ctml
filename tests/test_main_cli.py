"""
`main.py map` dispatch: which registries run, and where output goes.
Nothing is mapped; the bulk functions are patched.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import main

logger.remove()


def _run(*argv):
    with patch.object(sys, "argv", ["main.py", *argv]), \
         patch.object(main, "map_all") as nct, patch.object(main, "map_all_ctis") as ctis:
        main.main()
    return nct, ctis


class TestMapDispatch(unittest.TestCase):

    def test_source_all_maps_both_registries(self):
        nct, ctis = _run("map", "--all", "--source", "all", "--out", tempfile.mkdtemp())
        self.assertTrue(nct.called and ctis.called)

    def test_default_source_is_nct_only(self):
        nct, ctis = _run("map", "--all", "--out", tempfile.mkdtemp())
        self.assertTrue(nct.called)
        self.assertFalse(ctis.called)

    def test_out_is_where_output_goes(self):
        out = tempfile.mkdtemp()
        nct, _ = _run("map", "--all", "--out", out)
        self.assertEqual(nct.call_args.args[1], out)

    def test_test_mode_never_writes_where_the_index_reads(self):
        with patch("os.makedirs"):
            nct, _ = _run("map", "--all", "--test_mode")
        path = nct.call_args.args[1]
        self.assertTrue(path.startswith(os.path.join("cache", "ctml_test")), path)
        self.assertNotEqual(os.path.normpath(path), os.path.normpath(config.CTML_MAPPED_PATH))


if __name__ == "__main__":
    unittest.main()
