"""Roadmap 2.8: what text the diagnosis step is given (config.DIAGNOSIS_INPUT)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import config
import src.mapping.diagnosis as diagnosis
import utils.llm.prompts.diagnosis as dx_prompts

logger.remove()

INC, EXC = "Newly diagnosed AML.", "Juvenile myelomonocytic leukemia (JMML). APL."


class TestDiagnosisText(unittest.TestCase):
    def test_legacy_returns_the_old_text_unchanged(self):
        with mock.patch.object(config, "DIAGNOSIS_INPUT", "legacy"):
            self.assertEqual(diagnosis.diagnosis_text(INC, EXC, "T", ["AML"], legacy="OLD"), "OLD")

    def test_labelled_labels_both_sections(self):
        with mock.patch.object(config, "DIAGNOSIS_INPUT", "labelled"):
            t = diagnosis.diagnosis_text(INC, EXC, conditions=["AML"], legacy="OLD")
        self.assertEqual(
            t,
            "Conditions: AML\nInclusion Criteria: Newly diagnosed AML.\n"
            "Exclusion Criteria: Juvenile myelomonocytic leukemia (JMML). APL.",
        )

    def test_inclusion_only_drops_the_exclusion_criteria(self):
        with mock.patch.object(config, "DIAGNOSIS_INPUT", "inclusion_only"):
            t = diagnosis.diagnosis_text(
                INC, EXC, title="CHIP-AML22", conditions=["AML"], legacy="OLD"
            )
        self.assertEqual(
            t, "Title: CHIP-AML22\nConditions: AML\nInclusion Criteria: Newly diagnosed AML."
        )
        self.assertNotIn("JMML", t)


class TestPromptRule(unittest.TestCase):
    def test_only_labelled_adds_the_exclusion_rule(self):
        for mode, expected in (("legacy", False), ("inclusion_only", False), ("labelled", True)):
            with mock.patch.object(config, "DIAGNOSIS_INPUT", mode):
                _, p = dx_prompts.get_ai_prompt_oncotree_diagnoses_from_trial_info(
                    "x", ["Acute Myeloid Leukemia"], "T"
                )
            self.assertEqual("excluded from the trial" in p, expected, mode)


if __name__ == "__main__":
    unittest.main()
