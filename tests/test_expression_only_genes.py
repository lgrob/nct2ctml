import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from loguru import logger

import src.trial_config as trial_config
from utils.reference_validation import filter_genomic_criteria

logger.remove()  # the filter logs every drop; tests assert on return values


def _genomic(symbol, variant_category="Mutation"):
    return {"genomic": {"hugo_symbol": symbol, "variant_category": variant_category}}


def _symbols(entries):
    return [e["genomic"]["hugo_symbol"] for e in entries]


class TestExpressionOnlyGenes(unittest.TestCase):
    """
    An antigen is measured by flow or IHC; MatchMiner's genomic path matches a
    sequencing report. Emitting "CD19+ ALL" as a required CD19 mutation gives a
    trial that matches no patient at all - and a trial that matches nobody is
    the one failure a reviewer cannot see.
    """

    def test_antigens_are_dropped(self):
        kept = filter_genomic_criteria(
            [_genomic("CD19"), _genomic("CD22"), _genomic("CTAG1B")], "NCT0")
        self.assertEqual(kept, [])

    def test_real_criteria_survive_beside_them(self):
        kept = filter_genomic_criteria(
            [_genomic("CD19"), _genomic("BRAF"),
             _genomic("MYCN", "Copy Number Variation")], "NCT0")
        self.assertEqual(_symbols(kept), ["BRAF", "MYCN"])

    def test_the_list_stays_narrow(self):
        """
        CD74 is the counter-example that keeps this honest: it appeared as a
        false positive in a benchmark run, but it forms real fusions
        (CD74-ROS1, CD74-NRG1) that a trial can legitimately require, so it
        must not be blocked.
        """
        self.assertEqual(_symbols(filter_genomic_criteria([_genomic("CD74")])),
                         ["CD74"])
        self.assertNotIn("CD74", trial_config.expression_only_genes)
        self.assertLess(len(trial_config.expression_only_genes), 15)

    def test_no_curated_answer_requires_one(self):
        """If a key ever needs one of these, the list is wrong, not the key."""
        import glob
        import yaml

        def walk(node):
            if isinstance(node, dict):
                if "hugo_symbol" in node:
                    yield node["hugo_symbol"]
                for v in node.values():
                    yield from walk(v)
            elif isinstance(node, list):
                for v in node:
                    yield from walk(v)

        blocked = {g.upper() for g in trial_config.expression_only_genes}
        root = os.path.join(os.path.dirname(__file__), "..", "ctml", "reviewed")
        offenders = []
        for path in sorted(glob.glob(os.path.join(root, "*.yaml"))):
            for symbol in walk(yaml.safe_load(open(path))):
                if str(symbol).upper() in blocked:
                    offenders.append(f"{os.path.basename(path)}: {symbol}")
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
