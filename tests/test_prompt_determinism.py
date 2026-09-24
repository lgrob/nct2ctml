"""
Roadmap 1.9: prompts and output must not depend on PYTHONHASHSEED.

Lists printed into prompts used to follow set order. Measured before the fix
on the 55 reviewed trials, seeds 0 vs 1: every level-1 and diagnosis prompt
differed, 67 of 119 genomic prompts differed, and the mapped output of 46
trials differed. The probe maps real cached trials with a stub model that
answers from the schema alone, under two seeds, and compares hashes of every
prompt, schema and output.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from loguru import logger

import utils.ai_helper as ai

logger.remove()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Chosen to exercise every prompt family, the genomic path included.
TRIALS = ["NCT07012447", "NCT03643276", "NCT05918640", "NCT04732065", "2023-503322-39-00"]


def _probe(seed):
    out = tempfile.mktemp(suffix=".json")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}
    env["PYTHONHASHSEED"] = str(seed)
    subprocess.run([sys.executable, os.path.join(ROOT, "tests", "determinism_probe.py"), out, ",".join(TRIALS)],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    return json.load(open(out))


class TestPromptDeterminism(unittest.TestCase):

    @unittest.skipUnless(all(os.path.exists(os.path.join(ROOT, "cache", "nct" if t.startswith("NCT") else "ctis", t + ".json"))
                             for t in TRIALS), "trial cache not present")
    def test_prompts_and_output_are_identical_across_hash_seeds(self):
        a, b = _probe(0), _probe(1)
        self.assertGreater(a.pop("_genomic_calls"), 0, "probe did not reach the genomic prompts")
        b.pop("_genomic_calls")
        for t in TRIALS:
            self.assertEqual(a[t]["ctml_err"], "", t)
            self.assertEqual([(c["p"], c["s"]) for c in a[t]["calls"]], [(c["p"], c["s"]) for c in b[t]["calls"]], t)
            self.assertEqual(a[t]["ctml"], b[t]["ctml"], t)


class TestPromptList(unittest.TestCase):

    def test_sorted_deduplicated_and_none_free(self):
        self.assertEqual(ai.prompt_list({"b", "a", None, "a"}), ["a", "b"])

    def test_diagnosis_candidates_are_printed_in_the_fixed_shuffle(self):
        import hashlib
        names = {"Neuroblastoma", "Ganglioneuroblastoma", "Medulloblastoma", "Ependymoma"}
        want = sorted(names, key=lambda v: hashlib.sha256(v.encode()).hexdigest())
        self.assertEqual(ai.diagnosis_prompt_list(names), want)
        for build in (lambda v: ai.get_ai_prompt_oncotree_diagnoses_from_trial_info("x", v, "T"),
                      lambda v: ai.get_ai_prompt_child_values("x", v, "T"),
                      lambda v: ai.get_ai_prompt_level1_for_original_conditions(["x"], v, "T")):
            self.assertIn(str(want), build(names)[1])

    def test_the_shuffle_does_not_move_existing_names_when_one_is_added(self):
        names = ["Neuroblastoma", "Ganglioneuroblastoma", "Medulloblastoma", "Ependymoma"]
        before = ai.diagnosis_prompt_list(names)
        after = [v for v in ai.diagnosis_prompt_list(names + ["Ganglioneuroma"]) if v != "Ganglioneuroma"]
        self.assertEqual(before, after)

    def test_gene_list_is_printed_sorted(self):
        _, p = ai.get_inclusion_genomic_criteria_prompt({"TP53", "ALK", "BRAF"}, "text")
        self.assertIn("['ALK', 'BRAF', 'TP53']", p)


if __name__ == "__main__":
    unittest.main()
