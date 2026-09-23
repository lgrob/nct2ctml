"""
Age bounds from eligibility prose, and how they combine with the structured
fields. Offline: the model's answer is given directly, never requested.

The structured maximumAge is in completed units for most sponsors and an
exclusive bound for about one in three; only the prose says which. Each case
below is a trial the repository's own docs cite.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.clinical_trials_gov as ctg
import src.ctis as ctis
import utils.age_bounds as ab


def _trial(minimum=None, maximum=None):
    eligibility = {}
    if minimum is not None:
        eligibility["minimumAge"] = minimum
    if maximum is not None:
        eligibility["maximumAge"] = maximum
    return {"protocolSection": {"identificationModule": {"nctId": "NCT00000000"},
                                "eligibilityModule": eligibility}}


def _prose(low=None, low_unit="years", low_inc=True, high=None, high_unit="years", high_inc=True):
    return {"minimum": {"value": low, "unit": low_unit, "inclusive": low_inc},
            "maximum": {"value": high, "unit": high_unit, "inclusive": high_inc}}


class TestStructuredAndProse(unittest.TestCase):

    def test_no_prose_is_the_structured_reading_unchanged(self):
        self.assertEqual(ctg.map_age_numerical(_trial("1 Year", "17 Years")),
                         ctg.map_age_numerical(_trial("1 Year", "17 Years"), None))
        self.assertEqual(ctg.map_age_numerical(_trial("1 Year", "17 Years")), [">=1", "<=18"])

    def test_an_exclusive_prose_bound_narrows_the_structured_maximum(self):
        # NCT06528691: "birth to age <3 years" against a structured "3 Years".
        got = ctg.map_age_numerical(_trial("0 Days", "3 Years"), _prose(high=3, high_inc=False))
        self.assertIn("<3", got)
        self.assertNotIn("<=4", got)

    def test_a_completed_units_prose_bound_keeps_the_wide_reading(self):
        # NCT02443831: "24 years or younger" against "24 Years".
        got = ctg.map_age_numerical(_trial(maximum="24 Years"), _prose(high=24, high_inc=True))
        self.assertEqual(got, ["<=25"])
        # NCT03643276: "age < 18 years" against "17 Years" - the same reading.
        got = ctg.map_age_numerical(_trial(maximum="17 Years"), _prose(high=18, high_inc=False))
        self.assertEqual(got, ["<=18"])

    def test_a_disagreeing_prose_bound_does_not_override(self):
        # Prose 30 against structured 18: probably a cohort or a misreading.
        # The structured field wins; the prose only ever resolves ambiguity.
        got = ctg.map_age_numerical(_trial(maximum="18 Years"), _prose(high=30, high_inc=False))
        self.assertEqual(got, ["<=19"])

    def test_prose_fills_bounds_the_structured_fields_lack(self):
        # NCT04625907 carries no structured ages; its key holds >=1 and <=25.
        got = ctg.map_age_numerical(_trial(), _prose(low=1, high=25, high_inc=True))
        self.assertEqual(got, [">=1", "<26"])

    def test_the_structured_minimum_is_not_overridden(self):
        got = ctg.map_age_numerical(_trial("1 Year"), _prose(low=2))
        self.assertEqual(got, [">=1"])

    def test_months_are_kept_in_months_for_the_completed_units_step(self):
        # "<= 18 months" admits a child until 19 months, not until 2.5 years.
        _, high = ab.prose_bounds(_prose(high=18, high_unit="months", high_inc=True))
        self.assertEqual(high, "<1.58")


class TestProseBounds(unittest.TestCase):

    def test_absent_bounds_are_none(self):
        self.assertEqual(ab.prose_bounds(_prose()), (None, None))
        self.assertEqual(ab.prose_bounds(None), (None, None))

    def test_birth_is_not_a_minimum(self):
        # NCT06528691: "birth to age <3 years".
        self.assertEqual(ab.prose_bounds(_prose(low=0, high=3, high_inc=False)), (None, "<3"))

    def test_an_inverted_range_is_dropped(self):
        self.assertEqual(ab.prose_bounds(_prose(low=21, high=1)), (None, None))

    def test_implausible_values_are_dropped(self):
        self.assertEqual(ab.prose_bounds(_prose(low=2019)), (None, None))

    def test_an_exclusive_minimum_keeps_its_operator(self):
        self.assertEqual(ab.prose_bounds(_prose(low=1, low_inc=False))[0], ">1")

    def test_an_unknown_unit_is_dropped_not_guessed(self):
        self.assertEqual(ab.prose_bounds(_prose(low=3, low_unit="decades")), (None, None))


class TestReadingFailures(unittest.TestCase):

    def test_a_model_failure_is_none_not_an_exception(self):
        with patch("utils.ai_helper.get_age_bounds", side_effect=ConnectionError("down")):
            self.assertIsNone(ab.read_age_bounds("NCT00000000", "Age 1 to 21 years"))

    def test_empty_text_asks_nothing(self):
        with patch("utils.ai_helper.get_age_bounds") as reader:
            self.assertIsNone(ab.read_age_bounds("NCT00000000", "  "))
        reader.assert_not_called()


class TestCtisBothBounds(unittest.TestCase):

    def test_ctis_now_gets_a_maximum(self):
        with patch("utils.ai_helper.get_age_bounds",
                   return_value=_prose(low=1, high=18, high_inc=False)):
            self.assertEqual(ctis.map_age_numerical("2023-500000-00-00", "Age 1 to <18 years"),
                             [">=1", "<18"])

    def test_ctis_with_no_stated_age_gets_none(self):
        with patch("utils.ai_helper.get_age_bounds", return_value=_prose()):
            self.assertEqual(ctis.map_age_numerical("2023-500000-00-00", "ECOG 0-1"), [])


if __name__ == "__main__":
    unittest.main()
