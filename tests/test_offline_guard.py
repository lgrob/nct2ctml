"""
The offline suite cannot call a model: utils.ai_helper's platform is wrapped
so that sending raises (tests/support.py). Without the guard, a stub that
stops taking effect - a patch on a function that has moved - would send
real requests.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import utils.ai_helper as ai
from tests.support import LIVE, OfflinePlatform


@unittest.skipIf(LIVE, "live LLM tests requested")
class TestOfflineGuard(unittest.TestCase):
    def test_the_guard_is_installed(self):
        self.assertIsInstance(
            ai._llm_platform,
            OfflinePlatform,
            "run the suite as `python -m unittest discover -s tests -t .` so that "
            "tests/__init__.py installs the offline guard",
        )

    def test_an_unstubbed_call_fails_instead_of_reaching_the_model(self):
        with self.assertRaisesRegex(RuntimeError, "reached the LLM platform"):
            ai.send_ai_request("NCT0", "prompt", {"type": "object"})

    def test_a_patch_on_a_name_that_does_not_exist_is_caught(self):
        # What a moved function leaves behind: the assignment succeeds and
        # patches nothing, and the real path runs - into the guard.
        with mock.patch.object(ai, "send_ai_request_moved", create=True, new=lambda *a: {}):
            with self.assertRaises(RuntimeError):
                ai.get_pdl1_status("NCT0", "PD-L1 positive", ["PD-L1"])

    def test_building_a_request_still_works(self):
        body = ai._llm_platform.get_request_body("p", ai.PDL1_SCHEMA)
        self.assertTrue(body)


if __name__ == "__main__":
    unittest.main()
