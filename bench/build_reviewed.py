"""
Rebuild the hand-curated answer key in ctml/reviewed/ from bench/curations.py.

The answer key is what the benchmark scores against, so it must not come from
the model it is judging. Everything the scorer looks at - the `age` label and
the clinical/genomic blocks in the match tree - is hand-written in
bench/curations.py after reading the trial's own eligibility text. Everything
it ignores - titles, arms, drugs, sponsor - comes from the pipeline's
deterministic mapping of the cached ClinicalTrials.gov record, which involves
no LLM.

Keeping the curated part as data rather than as 50 hand-maintained YAML files
means a schema change does not require re-editing every file, and the
provenance of each answer stays visible next to it.

    python -m bench.build_reviewed            # write every curated trial
    python -m bench.build_reviewed --check    # verify without writing
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

import src.clinical_trials_gov as ctg
import src.ctml_schema as cs
import src.trial_data_helper as tdh
from bench.curations import CURATIONS
from utils.reference_validation import canonical_diagnosis, canonical_gene

CACHE_DIR = "cache/nct"
OUT_DIR = "ctml/reviewed"


def walk(node, want):
    if isinstance(node, dict):
        if want in node and isinstance(node[want], dict):
            yield node[want]
        for value in node.values():
            yield from walk(value, want)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value, want)


def validate(nct_id, match):
    """Every curated term must exist. A typo in the answer key is worse than a
    typo in the output: it silently marks a correct answer wrong forever."""
    problems = []
    for clinical in walk(match, "clinical"):
        term = clinical.get("oncotree_primary_diagnosis")
        if term and canonical_diagnosis(term) != term:
            problems.append(f"{nct_id}: diagnosis {term!r} is not an Oncotree display name")
    for genomic in walk(match, "genomic"):
        symbol = genomic.get("hugo_symbol")
        if symbol and canonical_gene(symbol) != symbol:
            problems.append(f"{nct_id}: gene {symbol!r} is not in the gene list")
    return problems


def _first_curated_on(nct_id):
    """
    Keep the date a trial was first curated rather than restamping it.

    Re-stamping makes every rebuild touch every file, so a real change to one
    answer hides among 49 date bumps.
    """
    path = f"{OUT_DIR}/{nct_id}.yaml"
    if os.path.exists(path):
        with open(path) as handle:
            for line in handle:
                if line.startswith("curated_on:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
    return datetime.date.today().isoformat()


def build(nct_id, curation):
    trial_data = tdh.read_from_file(CACHE_DIR, nct_id, "json")
    schema = cs.get_ctml_schema()
    schema = ctg.map_ctml_general_fields(schema, trial_data)
    schema = ctg.map_prior_treatment_requirements(schema, trial_data)
    # The pipeline collects drugs into a set, so their order changes with
    # Python's hash seed on every run. Sort them: an answer key nobody can
    # diff is an answer key nobody will review.
    drugs = (schema.get("drug_list") or {}).get("drug")
    if isinstance(drugs, list):
        drugs.sort(key=lambda d: str((d or {}).get("drug_name", "")))
    schema["age"] = curation["age"]
    schema["curated_on"] = curation.get("curated_on", _first_curated_on(nct_id))
    steps = schema.setdefault("treatment_list", {}).setdefault("step", [])
    if not steps:
        steps.append({"step_internal_id": 1, "step_code": "1",
                      "step_type": "Registration", "match": [], "arm": []})
    steps[0]["match"] = curation["match"]
    return schema


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="validate the curated terms without writing files")
    args = ap.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    problems, written = [], 0
    for nct_id, curation in sorted(CURATIONS.items()):
        if not os.path.exists(f"{CACHE_DIR}/{nct_id}.json"):
            problems.append(f"{nct_id}: not in {CACHE_DIR}")
            continue
        problems.extend(validate(nct_id, curation["match"]))
        if args.check:
            continue
        schema = build(nct_id, curation)
        tdh.save_to_file(schema, OUT_DIR, nct_id, "yaml")
        written += 1

    for problem in problems:
        print(f"  INVALID  {problem}")
    print(f"\n{len(CURATIONS)} curated trials, "
          f"{len(problems)} invalid term(s)"
          + ("" if args.check else f", {written} written to {OUT_DIR}"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
