"""
Review support (2026-10-03): the text gaps on the sheet (utils/review/alignment.py),
the queue order (utils/review/priority.py) and audit confirmation
(utils/review/audit_confirm.py).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.review.alignment as alignment
import utils.review.audit_confirm as audit_confirm
import utils.review.priority as priority

logger.remove()


def trial(diagnoses, ages=(), genes=()):
    nodes = [{"clinical": {"oncotree_primary_diagnosis": d}} for d in diagnoses]
    nodes += [{"clinical": {"age_numerical": a}} for a in ages]
    nodes += [{"genomic": {"hugo_symbol": g, "variant_category": "Mutation"}} for g in genes]
    return {"treatment_list": {"step": [{"match": [{"and": nodes}]}]}}


class TestTextGaps(unittest.TestCase):
    def kinds(self, ctml, **sections):
        return {(g.kind, g.term.lower()) for g in alignment.gaps(ctml, sections)}

    def test_a_named_population_that_is_not_published(self):
        # NCT07680205: paraganglioma named, pheochromocytoma published.
        gaps = alignment.gaps(
            trial(["Pheochromocytoma"]),
            {"inclusion": "confirmed phaeochromocytoma or paraganglioma"},
        )
        named = [g for g in gaps if g.kind == "named, not published"]
        self.assertTrue(any("Paraganglioma" in g.targets for g in named))
        self.assertIn("1 of 2 codes published", [g.status for g in named])

    def test_a_published_parent_covers_its_children(self):
        found = self.kinds(trial(["Acute Myeloid Leukemia"]), inclusion="AML with mutated NPM1")
        self.assertEqual({k for k in found if k[0] == "named, not published"}, set())

    def test_an_exclusion_the_published_diagnoses_still_admit(self):
        # NCT04318678: APL excluded, AML published without !APL.
        found = self.kinds(
            trial(["Acute Myeloid Leukemia"]), exclusion="acute promyelocytic leukemia"
        )
        self.assertIn(("excluded in text, still admitted", "acute promyelocytic leukemia"), found)
        written = trial(["Acute Myeloid Leukemia", "!APL with PML-RARA"])
        self.assertEqual(self.kinds(written, exclusion="acute promyelocytic leukemia"), set())

    def test_an_exclusion_inside_the_inclusion_text(self):
        # 2024-512135-80-00: "solid malignancy excluding osteosarcoma" published as _SOLID_.
        found = self.kinds(
            trial(["_SOLID_"]), inclusion="relapsed solid malignancy excluding osteosarcoma"
        )
        self.assertIn(("excluded in text, still admitted", "osteosarcoma"), found)

    def test_organ_words_are_not_populations(self):
        self.assertEqual(
            self.kinds(trial(["Neuroblastoma"]), inclusion="no bone or liver involvement"), set()
        )

    def test_a_gene_stated_with_an_alteration_and_not_used(self):
        found = self.kinds(trial(["Neuroblastoma"]), inclusion="tumour with ALK mutation")
        self.assertIn(("gene not used", "alk"), found)
        self.assertEqual(
            self.kinds(trial(["Neuroblastoma"], genes=["ALK"]), inclusion="ALK mutation"), set()
        )

    def test_stated_ages(self):
        self.assertEqual(
            alignment.stated_ages({"inclusion": "Age 1 to 21 years. Consent."}),
            ["Age 1 to 21 years"],
        )


class TestQueueOrder(unittest.TestCase):
    def test_an_open_paediatric_trial_outranks_a_closed_adult_one(self):
        with mock.patch.object(priority, "_status", return_value={"A": "open", "B": "closed"}):
            child, why = priority.score(
                "A", trial(["Neuroblastoma"], ages=[">=1", "<22"]), ["age_registry_conflict"]
            )
            adult, _ = priority.score("B", trial(["Prostate Adenocarcinoma"], ages=[">=18"]))
        self.assertGreater(child, adult)
        self.assertIn("+2 paediatric diagnosis", why)
        self.assertIn("+1 usually a quick fix", why)

    def test_a_kispi_trial_counts_most(self):
        with (
            mock.patch.object(priority, "_status", return_value={}),
            mock.patch.object(priority, "_kispi_trials", return_value=frozenset({"NCT1"})),
        ):
            points, why = priority.score("NCT1", trial(["Neuroblastoma"]))
        self.assertIn("+5 Kispi trial", why)


class TestAuditConfirmation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        audit = os.path.join(self.dir, "audit.tsv")
        with open(audit, "w") as f:
            f.write("trial_id\tverdict\teffect\tcause\tnote\n")
            for i in range(4):
                f.write(f"E{i}\terror\tloses\tmissing-diagnosis\tnote\n")
            for i in range(6):
                f.write(f"C{i}\tcorrect\t\t\tnote\n")
            f.write("B0\tborderline\t\t\tnote\n")
        self.patches = [
            mock.patch.object(audit_confirm, "AUDIT_TSV", audit),
            mock.patch.object(audit_confirm, "CONFIRM_TSV", os.path.join(self.dir, "conf.tsv")),
            mock.patch.object(audit_confirm, "CORRECT_SAMPLE", 2),
        ]
        for p in self.patches:
            p.start()
        audit_confirm.audit_rows.cache_clear()
        audit_confirm.sample.cache_clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        audit_confirm.audit_rows.cache_clear()
        audit_confirm.sample.cache_clear()

    def test_the_sample_is_every_flagged_trial_and_some_correct_ones(self):
        s = audit_confirm.sample()
        self.assertEqual(len(s), 4 + 1 + 2)
        self.assertEqual(s, audit_confirm.sample())  # seeded

    def test_a_verdict_is_recorded_and_the_last_one_counts(self):
        self.assertFalse(audit_confirm.record("E0", "", "error", "loses")[0])
        self.assertFalse(audit_confirm.record("E0", "ana", "error", "")[0])
        self.assertTrue(audit_confirm.record("E0", "ana", "error", "loses")[0])
        self.assertTrue(audit_confirm.record("E0", "ana", "correct", "", saw_ai=True)[0])
        self.assertEqual(audit_confirm.confirmations()["E0"]["verdict"], "correct")
        self.assertEqual(audit_confirm.confirmations()["E0"]["saw_ai"], "yes")

    def test_rates_are_weighted_back_to_the_audit(self):
        for t in ("E0", "E1"):
            audit_confirm.record(t, "ana", "error", "loses")
        audit_confirm.record("B0", "ana", "borderline", "")
        for t in audit_confirm.sample():
            if t.startswith("C"):
                audit_confirm.record(t, "ana", "correct", "")
        s = audit_confirm.summary()
        # 4 AI errors confirmed at 100%, 1 borderline at 0%, 6 correct at 0% -> 4/11.
        self.assertAlmostEqual(s["loses_rate"][0], 4 / 11)
        self.assertEqual(s["agree"]["error"], (2, 2, 2))

    def test_no_estimate_before_every_stratum_is_seen(self):
        audit_confirm.record("E0", "ana", "error", "loses")
        self.assertIsNone(audit_confirm.summary()["loses_rate"])

    def test_the_audited_version_is_read_from_the_release(self):
        if not os.path.exists(f"releases/{audit_confirm.RELEASE}.tar.gz"):
            self.skipTest("release archive not present")
        with mock.patch.object(audit_confirm, "AUDIT_TSV", "ctml/audit_2026-10-03.tsv"):
            audit_confirm.audit_rows.cache_clear()
            t = next(iter(audit_confirm.audit_rows()))
            self.assertIn("treatment_list", audit_confirm.basis_ctml(t))
            self.assertTrue(audit_confirm.criteria_lines(audit_confirm.basis_ctml(t)))
