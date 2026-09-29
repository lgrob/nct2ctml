"""
The index tables' columns are the fields of their row types
(utils/build_trial_index.TrialRow, DiagnosisRow, GenomicRow), and a built
index has exactly those columns, in that order.
"""

import csv
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils import build_trial_index as bti

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRIAL = "NCT03643276"


class TestRowTypes(unittest.TestCase):
    def test_columns_are_the_row_type_fields(self):
        self.assertEqual(bti.TRIAL_COLUMNS, list(bti.TrialRow.__annotations__))
        self.assertEqual(bti.DIAGNOSIS_COLUMNS, list(bti.DiagnosisRow.__annotations__))
        self.assertEqual(bti.GENOMIC_COLUMNS, list(bti.GenomicRow.__annotations__))

    @unittest.skipUnless(
        os.path.exists(os.path.join(ROOT, "ctml", "reviewed", f"{TRIAL}.yaml")), "no curated trial"
    )
    def test_a_built_index_has_exactly_those_columns(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        layer = os.path.join(tmp, "layer")
        os.makedirs(layer)
        shutil.copy(os.path.join(ROOT, "ctml", "reviewed", f"{TRIAL}.yaml"), layer)
        out = os.path.join(tmp, "index")
        bti.build([(layer, "reviewed")], out)
        for name, row_type in (
            ("trials.tsv", bti.TrialRow),
            ("trial_diagnosis.tsv", bti.DiagnosisRow),
            ("trial_genomic.tsv", bti.GenomicRow),
        ):
            with open(os.path.join(out, name)) as handle:
                header = next(csv.reader(handle, delimiter="\t"))
            self.assertEqual(header, list(row_type.__annotations__), name)


if __name__ == "__main__":
    unittest.main()
