"""
Regression check for the deterministic diagnosis path, on frozen records.

    python -m bench.conditions_baseline            # compare with the baseline
    python -m bench.conditions_baseline --update   # accept the current output

Runs `benchmark_map --conditions-only` (seed plus basket rule, no model, no
network) over the curated NCT trials, reading their registry records from
tests/fixtures/registry/nct rather than cache/, which `pull` keeps changing.
Compares each trial's diagnoses and the mean scores with
bench/baseline_conditions_nct.json.

A difference is not necessarily a regression, but it is always a change in
what reaches the model as its diagnosis floor. Look at it, and if it is
intended, run --update and commit the new baseline with the change that
caused it. tests/test_benchmark_baseline.py runs the same comparison.
"""

import argparse
import json
import os
import sys
import tempfile
from statistics import mean
from unittest import mock

import yaml

from bench import benchmark_map as bm

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "registry", "nct")
BASELINE = os.path.join(ROOT, "bench", "baseline_conditions_nct.json")


def compute(fixtures=FIXTURES, truth=None):
    """{"trials": {id: [diagnoses]}, "means": {metric: value}} for the curated NCT trials."""
    truth = truth or os.path.join(ROOT, bm.TRUTH_DIR)
    ids = bm.trial_ids(truth, "nct")
    with tempfile.TemporaryDirectory() as out, mock.patch.dict(bm.CACHE_DIRS, {"nct": fixtures}):
        bm.write_conditions_baseline(ids, out)
        trials = {}
        for trial_id in ids:
            with open(os.path.join(out, f"{trial_id}.yaml")) as handle:
                trials[trial_id] = sorted(bm.facts(yaml.safe_load(handle))["diagnoses"])
        _, agg = bm.score(truth, out, ids)
    means = {
        k: round(mean(agg[k]), 4) for k in ("dx_p", "dx_r", "dx_f1", "pop_p", "pop_r", "pop_f1")
    }
    return {"trials": trials, "means": means}


def differences(current, baseline):
    """Human-readable differences between two compute() results; empty when equal."""
    out = []
    for trial_id in sorted(set(current["trials"]) | set(baseline["trials"])):
        now, then = current["trials"].get(trial_id), baseline["trials"].get(trial_id)
        if now != then:
            if then is None or now is None:
                out.append(f"{trial_id}: {'new' if then is None else 'gone'}")
                continue
            added, lost = sorted(set(now) - set(then)), sorted(set(then) - set(now))
            out.append(f"{trial_id}: +{added} -{lost}")
    for key in sorted(set(current["means"]) | set(baseline["means"])):
        if current["means"].get(key) != baseline["means"].get(key):
            out.append(f"mean {key}: {baseline['means'].get(key)} -> {current['means'].get(key)}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--update", action="store_true", help="write the current output as baseline")
    args = ap.parse_args(argv)

    current = compute()
    if args.update:
        with open(BASELINE, "w") as handle:
            json.dump(current, handle, indent=1, sort_keys=True)
            handle.write("\n")
        print(f"baseline written: {len(current['trials'])} trials, means {current['means']}")
        return 0
    with open(BASELINE) as handle:
        found = differences(current, json.load(handle))
    for line in found:
        print(line)
    if not found:
        print(f"{len(current['trials'])} trials match the baseline; means {current['means']}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
