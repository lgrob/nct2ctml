"""
The two age defects the 2026-09-29 audit found
(doc/runs/2026-09-29-3.4-audit.md).

A. The upper bound was published one unit too wide: the registry path added a
   completed unit to maximumAge and kept "<=", so a 40-year maximum became
   "<=41". Invisible in MatchMiner, which treats "<" and "<=" alike; the flat
   index reads the operator literally, and 496 of the 765 indexed trials with
   an upper bound admitted an extra year of patients.
B. Three trials inherit a sponsor's units error - the structured fields in
   days, the text in years - and were published as neonatal windows.

Offline: no model, no registry calls.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.clinical_trials_gov as ctg
import src.text_rules as text_rules
import utils.review.evidence as evidence
import utils.review.maintenance as maintenance
from src.trial_map_manager import TrialMapManager as M
from tests.support import temporary_layers


def _trial(minimum=None, maximum=None, criteria=""):
    eligibility = {"eligibilityCriteria": criteria}
    if minimum is not None:
        eligibility["minimumAge"] = minimum
    if maximum is not None:
        eligibility["maximumAge"] = maximum
    return {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT0TEST"},
            "eligibilityModule": eligibility,
        }
    }


class TestTheUpperBoundIsExclusive(unittest.TestCase):
    """Defect A, at the source."""

    def test_the_registry_maximum_is_emitted_as_exclusive(self):
        # maximumAge "40 Years" means age < 41. "<=41" admits a 41-year-old.
        self.assertEqual(ctg.map_age_numerical(_trial(maximum="40 Years")), ["<41"])

    def test_no_upper_bound_is_ever_inclusive(self):
        for stated in ("17 Years", "21 Years", "6 Months", "70 Days", "0 Days"):
            got = ctg.map_age_numerical(_trial(maximum=stated))
            self.assertTrue(got and got[0].startswith("<") and not got[0].startswith("<="), got)

    def test_the_minimum_keeps_its_inclusive_operator(self):
        self.assertEqual(ctg.map_age_numerical(_trial("14 Years", "40 Years")), [">=14", "<41"])


class TestAgeUnitsImplausible(unittest.TestCase):
    """Defect B, the rule."""

    def test_the_three_audited_trials_are_reported(self):
        # NCT06342336 and NCT07106892: 18/75 Days against 18-75 years.
        self.assertIn(
            "same numbers in years",
            text_rules.age_units_implausible(
                "18 Days", "75 Days", "1. Age: 18 years to 75 years at the time of consent;"
            ),
        )
        self.assertIn(
            "same numbers in years",
            text_rules.age_units_implausible(
                "18 Days", "75 Days", "* Aged >= 18 years AND <= 75 years at the time of signing"
            ),
        )
        # NCT06776952: 18/70 Days against "Aged 18-70 years (inclusive)".
        self.assertIn(
            "same numbers in years",
            text_rules.age_units_implausible(
                "18 Days", "70 Days", "* Aged 18-70 years (inclusive), gender not limited."
            ),
        )

    def test_the_reason_names_both_registry_values(self):
        reason = text_rules.age_units_implausible("18 Days", "75 Days", "Age 18 years to 75 years")
        self.assertIn("18 Days", reason)
        self.assertIn("75 Days", reason)

    def test_a_real_neonatal_trial_is_not_reported(self):
        self.assertEqual(
            text_rules.age_units_implausible(
                "18 Days", "70 Days", "Infants aged 18 to 70 days at enrolment."
            ),
            "",
        )

    def test_year_figures_that_are_not_the_bounds_are_not_reported(self):
        # A neonatal trial whose text mentions other year figures.
        self.assertEqual(
            text_rules.age_units_implausible(
                "18 Days",
                "70 Days",
                "Neonates 18 to 70 days old. No second malignancy within 2 years.",
            ),
            "",
        )

    def test_one_number_matching_is_not_enough(self):
        self.assertEqual(
            text_rules.age_units_implausible("18 Days", "70 Days", "Aged 18 years or older"), ""
        )

    def test_structured_years_are_never_reported(self):
        self.assertEqual(
            text_rules.age_units_implausible("18 Years", "75 Years", "Age 18 years to 75 years"), ""
        )

    def test_one_bound_alone_is_not_reported(self):
        self.assertEqual(text_rules.age_units_implausible("18 Days", None, "Age 18 years"), "")
        self.assertEqual(text_rules.age_units_implausible(None, "75 Days", "Age 75 years"), "")

    def test_missing_or_unparseable_fields_are_not_reported(self):
        self.assertEqual(text_rules.age_units_implausible("N/A", "N/A", "Age 18 years"), "")
        self.assertEqual(text_rules.age_units_implausible(None, None, None), "")


class TestTheMapperFlagsAndRoutes(unittest.TestCase):
    """Defect B, in the mapper: flagged, kept as the registry states it, queued."""

    CRITERIA = "Inclusion Criteria:\n\n1. Age: 18 years to 75 years at the time of consent;\n"

    def _mapped(self):
        trial = _trial("18 Days", "75 Days", self.CRITERIA)
        ctml = {
            "nct_id": "NCT0TEST",
            "treatment_list": {
                "step": [
                    {
                        "match": [
                            {
                                "clinical": {
                                    "oncotree_primary_diagnosis": "Colorectal Adenocarcinoma",
                                    "age_numerical": ">=0.05",
                                }
                            }
                        ]
                    }
                ]
            },
        }
        M._flag_age_units(ctml, trial, "NCT0TEST")
        return ctml

    def test_the_flag_is_written(self):
        self.assertIn("same numbers in years", self._mapped()["age_units_implausible"])

    def test_the_trial_goes_to_review(self):
        self.assertNotEqual(
            M._destination_for(self._mapped(), "cache/ctml", "NCT0TEST"), "cache/ctml"
        )

    def test_the_bounds_are_left_as_the_registry_states_them(self):
        # Which field the sponsor meant is a curator's call, not the mapper's.
        self.assertEqual(ctg.map_age_numerical(_trial("18 Days", "75 Days")), [">=0.05", "<0.21"])

    def test_a_plausible_trial_is_not_flagged(self):
        ctml = {"nct_id": "NCT0TEST"}
        M._flag_age_units(ctml, _trial("1 Year", "17 Years", self.CRITERIA), "NCT0TEST")
        self.assertNotIn("age_units_implausible", ctml)


class _Layers(unittest.TestCase):
    def setUp(self):
        self.layers = temporary_layers().__enter__()
        self.addCleanup(self.layers.__exit__, None, None, None)

    def put(self, text, layer="mapped"):
        directory = {
            "mapped": self.layers.mapped,
            "review": self.layers.review,
            "reviewed": self.layers.reviewed,
        }[layer]
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "NCT0TEST.yaml"), "w") as fh:
            fh.write(text)

    @staticmethod
    def _offline_scope():
        return (
            mock.patch("utils.oncology_scope.load_report", lambda *a, **k: {}),
            mock.patch("utils.oncology_scope.load_overrides", lambda *a, **k: {}),
        )


CTML = (
    "nct_id: NCT0TEST\n"
    "treatment_list:\n"
    "  step:\n"
    "  - match:\n"
    "    - and:\n"
    "      - clinical:\n"
    "          oncotree_primary_diagnosis: Neuroblastoma\n"
    "          age_numerical: '>=14'\n"
    "      - clinical:\n"
    "          age_numerical: {maximum}\n"
)


class TestFixAgeOperator(_Layers):
    """Defect A, re-applied to CTML written before the fix - no re-map."""

    def _run(self, maximum, apply=False, comment=""):
        self.put(comment + CTML.format(maximum=maximum))
        with self._offline_scope()[0], self._offline_scope()[1]:
            return maintenance.fix_age_operator(apply=apply)

    def test_an_inclusive_maximum_is_rewritten(self):
        found = self._run("<=41", apply=True)
        self.assertEqual(found, [("NCT0TEST", "mapped", [("<=41", "<41")])])
        written = open(os.path.join(self.layers.mapped, "NCT0TEST.yaml")).read()
        self.assertIn("age_numerical: <41", written)
        self.assertNotIn("<=41", written)

    def test_the_minimum_is_untouched(self):
        self._run("<=41", apply=True)
        self.assertIn(
            "age_numerical: '>=14'", open(os.path.join(self.layers.mapped, "NCT0TEST.yaml")).read()
        )

    def test_a_decimal_bound_is_rewritten(self):
        self.assertEqual(self._run("<=0.19")[0][2], [("<=0.19", "<0.19")])

    def test_an_already_exclusive_bound_is_left_alone(self):
        self.assertEqual(self._run("<41"), [])

    def test_the_dry_run_writes_nothing(self):
        self._run("<=41")
        self.assertIn("<=41", open(os.path.join(self.layers.mapped, "NCT0TEST.yaml")).read())

    def test_a_file_with_curator_comments_is_never_rewritten(self):
        self.assertEqual(self._run("<=41", apply=True, comment="# checked by lgrob\n"), [])

    def test_ctml_reviewed_is_never_touched(self):
        self.put(CTML.format(maximum="<=41"), layer="reviewed")
        with self._offline_scope()[0], self._offline_scope()[1]:
            self.assertEqual(maintenance.fix_age_operator(apply=True), [])


class TestFlagAgeUnitsPass(_Layers):
    """Defect B, re-applied to CTML written before the check."""

    TEXT = "Inclusion Criteria:\n\n1. Age: 18 years to 75 years;\n"

    def _run(self, minimum, maximum, apply=False):
        self.put(CTML.format(maximum="<0.21"))
        record = _trial(minimum, maximum, self.TEXT)
        with (
            mock.patch.object(evidence, "eligibility_text", lambda t: (self.TEXT, "", record)),
            self._offline_scope()[0],
            self._offline_scope()[1],
        ):
            return maintenance.flag_age_units(apply=apply)

    def test_a_days_against_years_trial_is_flagged_and_moved(self):
        found = self._run("18 Days", "75 Days", apply=True)
        self.assertEqual(
            [(t, layer, a) for t, layer, _, a in found], [("NCT0TEST", "mapped", "moved to review")]
        )
        self.assertFalse(os.path.exists(os.path.join(self.layers.mapped, "NCT0TEST.yaml")))
        moved = open(os.path.join(self.layers.review, "NCT0TEST.yaml")).read()
        self.assertIn("age_units_implausible:", moved)
        self.assertIn("age_numerical: <0.21", moved)  # the bounds are not rewritten

    def test_a_plausible_trial_is_not_flagged(self):
        self.assertEqual(self._run("1 Year", "17 Years"), [])

    def test_the_dry_run_writes_nothing(self):
        self._run("18 Days", "75 Days")
        self.assertTrue(os.path.exists(os.path.join(self.layers.mapped, "NCT0TEST.yaml")))
        self.assertFalse(os.path.exists(os.path.join(self.layers.review, "NCT0TEST.yaml")))


if __name__ == "__main__":
    unittest.main()
