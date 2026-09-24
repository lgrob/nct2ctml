"""
Benchmark the automated `map` stage against hand-curated CTML.

ctml/reviewed/*.yaml are curated by a human and verified end-to-end in
MatchMiner, so they serve as the answer key. This runs the pipeline over the
same trials and scores the result, so "is the LLM good enough to curate?" is
answered with numbers instead of impressions.

Both registries are scored: 50 keys are ClinicalTrials.gov trials (NCT ids)
and 5 are EU CTIS trials (EU CT numbers such as 2025-520982-39-00). Until
roadmap step 1.5 only the NCT keys were read, so the CTIS mapper - a
different document shape, its own condition accessor and no keyword or title
fallback - had no benchmark at all. Each report row carries its registry and
the summary gives a mean per registry, because 5 CTIS trials averaged into 50
NCT ones carry 5/55 of the overall mean's weight, so a CTIS regression
would barely move it.

Scoring is deliberately blunt and reported alongside the raw sets, because no
single number decides this - a reviewer needs to see what the model actually
said. Three dimensions:

  diagnoses  Oncotree terms, two ways: exact set comparison of the names, and
             comparison of the patient populations they reach - each side
             expanded to the Oncotree nodes a patient can be coded to (see
             utils.build_trial_index.diagnosis_population). The names are
             kept for continuity with earlier runs; the population is the
             one that says whether a patient reaches the trial.
  genes      hugo_symbol values, exact set comparison
  structure  does the tree contain a gene asserted both present and absent -
             the unsatisfiable shape that matches zero patients

Usage:
    python -m bench.benchmark_map                 # run the pipeline, then score
    python -m bench.benchmark_map --score-only    # score an existing output dir
    python -m bench.benchmark_map --out DIR       # where mapped CTML goes
    python -m bench.benchmark_map --limit N       # first N trials only
    python -m bench.benchmark_map --conditions-only
        # diagnoses from the trial's own conditions, no model, no network:
        # the deterministic floor, scored in seconds. Genes and ages are not
        # produced on this path and are not scored.
    python -m bench.benchmark_map --source nct    # one registry: nct | ctis | all
"""
import argparse, json, os, re, sys, time, yaml
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils.build_trial_index import diagnosis_population

TRUTH_DIR = config.CTML_REVIEWED_PATH
CACHE_DIRS = {"nct": config.NCT_CACHE_PATH, "ctis": config.CTIS_CACHE_PATH}
REGISTRIES = ("nct", "ctis")
# EU CT number: year, six-digit sequence, two two-digit suffixes.
_EU_CT_NUMBER = re.compile(r"^\d{4}-\d{6}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- registries
def registry_of(trial_id):
    """'nct', 'ctis', or None for a file in the key directory that is neither."""
    if trial_id.startswith("NCT"):
        return "nct"
    if _EU_CT_NUMBER.match(trial_id):
        return "ctis"
    return None


def trial_ids(truth_dir, source="all"):
    """
    The curated trial ids to score, NCT first, then CTIS.

    Registry order rather than a plain sort, because a plain sort puts every
    EU CT number ("2023-...") ahead of every NCT id, and `--limit N` would
    then silently stop meaning "the first N NCT trials" it meant before CTIS
    was scored.
    """
    ids = []
    for name in os.listdir(truth_dir):
        if not name.endswith(".yaml"):
            continue
        registry = registry_of(name[:-5])
        if registry and source in ("all", registry):
            ids.append(name[:-5])
    return sorted(ids, key=lambda t: (REGISTRIES.index(registry_of(t)), t))


def conditions_of(trial_id, record):
    """
    The trial's own condition list, from whichever document shape it has.

    CTIS has no conditionsModule; its conditions are the medicalConditions of
    authorizedPartI, read by the same accessor src/ctis.map_ctis_to_ctml uses,
    so the floor scored here is the floor the CTIS mapper hands the model.
    """
    if registry_of(trial_id) == "ctis":
        import src.ctis as ctis
        return ctis.get_conditions(record)
    return (record.get("protocolSection", {}).get("conditionsModule", {})
            .get("conditions", []))


def map_trial(mgr, trial_id, out_dir):
    """Run the registry's own full mapper for one trial; True on success."""
    if registry_of(trial_id) == "ctis":
        return mgr.map_single_ctis_trial(trial_id, CACHE_DIRS["ctis"], out_dir)
    return mgr.map_single_trial(trial_id, CACHE_DIRS["nct"], out_dir)


# ---------------------------------------------------------------- extraction
def walk(node, want):
    """Yield every `want` ('clinical' or 'genomic') block in a match tree."""
    if isinstance(node, dict):
        if want in node and isinstance(node[want], dict):
            yield node[want]
        for v in node.values():
            yield from walk(v, want)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, want)


def _age_key(expr):
    """
    An age bound in the form MatchMiner actually compares.

    Its query transformer maps "<" and "<=" to the same Mongo operator, and
    ">" and ">=" likewise, so `<18` and `<=18` select identical patients. The
    key must not treat them as different answers.
    """
    text = str(expr).strip()
    if text.startswith(("<", ">")) and not text.startswith(("<=", ">=")):
        return text[0] + "=" + text[1:]
    return text


def facts(doc):
    """Reduce a CTML document to the things worth comparing."""
    steps = (doc.get("treatment_list") or {}).get("step") or []
    matches = [m for st in steps for m in (st.get("match") or [])]
    diagnoses, genes, ages = set(), set(), set()
    for m in matches:
        for c in walk(m, "clinical"):
            if c.get("oncotree_primary_diagnosis"):
                diagnoses.add(str(c["oncotree_primary_diagnosis"]).strip())
            if c.get("age_numerical"):
                ages.add(_age_key(c["age_numerical"]))
        for g in walk(m, "genomic"):
            if g.get("hugo_symbol"):
                genes.add(str(g["hugo_symbol"]).strip())
    return {"diagnoses": diagnoses, "genes": genes, "ages": ages,
            "age_label": doc.get("age"), "matches": matches}


def unsatisfiable(matches):
    """
    Genes asserted both present and absent inside the same AND branch.

    Only genes every path through the AND requires count: a gene inside an
    OR under the AND is one alternative, not a requirement. The Ewing CTIS
    keys (2023-503322-39-00, 2024-511989-36-00) require an EWSR1 fusion in
    one alternative and its absence in another, which is satisfiable, and
    were flagged until 2026-09-24.
    """
    out = set()

    def required(node):
        if isinstance(node, dict):
            if isinstance(node.get("genomic"), dict):
                yield node["genomic"]
            for k, v in node.items():
                if k != "or":
                    yield from required(v)
        elif isinstance(node, list):
            for v in node:
                yield from required(v)

    def check(node):
        if isinstance(node, dict):
            if "and" in node and isinstance(node["and"], list):
                pos, neg = set(), set()
                for child in node["and"]:
                    for g in required(child):
                        sym = g.get("hugo_symbol")
                        vc = str(g.get("variant_category", ""))
                        if not sym:
                            continue
                        (neg if vc.startswith("!") else pos).add(sym)
                out.update(pos & neg)
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    for m in matches:
        check(m)
    return out


def prf(got, want):
    if not got and not want:
        return 1.0, 1.0, 1.0
    tp = len(got & want)
    p = tp / len(got) if got else 0.0
    r = tp / len(want) if want else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def population_prf(got, want):
    """
    Precision and recall over the patients each diagnosis set reaches.

    Recall is the share of the key's patients the output also reaches - a
    miss is a patient who never sees a trial they qualify for. Precision is
    the share of the output's patients the key agrees with - a miss is a
    clinician rejecting a trial by hand. They are reported apart because the
    two errors do not cost the same, and F1 is carried only for comparison.
    Every codable node counts once; a rare subtype weighs as much as a common
    one, which is the thing a patient-frequency weighting would change.
    """
    reached, wanted = diagnosis_population(got), diagnosis_population(want)
    return prf(reached, wanted) + (reached, wanted)


# ---------------------------------------------------------------- reporting
def score(truth_dir, out_dir, ids):
    rows, agg = [], defaultdict(list)
    for nct in ids:
        tp, op = f"{truth_dir}/{nct}.yaml", f"{out_dir}/{nct}.yaml"
        if not os.path.exists(op):
            rows.append({"nct_id": nct, "registry": registry_of(nct),
                         "status": "MISSING OUTPUT"})
            continue
        t, o = facts(yaml.safe_load(open(tp))), facts(yaml.safe_load(open(op)))
        dp, dr, df = prf(o["diagnoses"], t["diagnoses"])
        pp, pr, pf, reached, wanted = population_prf(o["diagnoses"], t["diagnoses"])
        gp, gr, gf = prf(o["genes"], t["genes"])
        uns = unsatisfiable(o["matches"])
        ap_, ar_, af_ = prf(o["ages"], t["ages"])
        rows.append({
            "nct_id": nct, "registry": registry_of(nct), "status": "ok",
            "dx_p": dp, "dx_r": dr, "dx_f1": df,
            "pop_p": pp, "pop_r": pr, "pop_f1": pf,
            "n_pop_truth": len(wanted), "n_pop_got": len(reached),
            "pop_missed": sorted(wanted - reached)[:6],
            "pop_extra": sorted(reached - wanted)[:6],
            "gene_p": gp, "gene_r": gr, "gene_f1": gf,
            "n_dx_truth": len(t["diagnoses"]), "n_dx_got": len(o["diagnoses"]),
            "genes_truth": sorted(t["genes"]), "genes_got": sorted(o["genes"]),
            "dx_missed": sorted(t["diagnoses"] - o["diagnoses"])[:6],
            "dx_spurious": sorted(o["diagnoses"] - t["diagnoses"])[:6],
            "age_truth": t["age_label"], "age_got": o["age_label"],
            "age_f1": af_, "age_p": ap_, "age_r": ar_,
            "ages_truth": sorted(t["ages"]), "ages_got": sorted(o["ages"]),
            "unsatisfiable": sorted(uns),
        })
        for k in ("dx_f1", "gene_f1", "age_f1", "dx_p", "dx_r", "gene_p", "gene_r",
                  "pop_p", "pop_r", "pop_f1"):
            agg[k].append(rows[-1][k])
    return rows, agg


MEAN_KEYS = ("dx_f1", "dx_p", "dx_r", "pop_p", "pop_r", "pop_f1", "gene_f1", "age_f1")


def registry_means(rows):
    """
    Mean of each score over the scored rows, overall and per registry:
    {"all": {...}, "nct": {...}, "ctis": {...}}, each with its row count `n`.
    A registry with no scored row is absent rather than reported as zero.
    """
    ok = [r for r in rows if r["status"] == "ok"]
    groups = {"all": ok}
    for registry in REGISTRIES:
        groups[registry] = [r for r in ok if r.get("registry") == registry]
    out = {}
    for name, rs in groups.items():
        if rs:
            out[name] = {k: sum(r[k] for r in rs) / len(rs) for k in MEAN_KEYS}
            out[name]["n"] = len(rs)
            out[name]["exact_dx"] = sum(1 for r in rs if r["dx_f1"] == 1.0)
            out[name]["exact_pop"] = sum(1 for r in rs if r["pop_f1"] == 1.0)
    return out


def report(rows, agg, diagnoses_only=False):
    ok = [r for r in rows if r["status"] == "ok"]
    width = 104
    print(f"\n{'trial':<19}{'reg':<5}{'dx F1':>7}{'dx P':>7}{'dx R':>7}{'pop P':>7}{'pop R':>7}"
          f"{'gene F1':>9}{'age F1':>8}{'#dx':>6}  flags")
    print("-" * width)
    for r in rows:
        if r["status"] != "ok":
            print(f"{r['nct_id']:<19}{r.get('registry') or '?':<5}{r['status']}")
            continue
        flags = []
        if r["unsatisfiable"]:
            flags.append("UNSATISFIABLE:" + ",".join(r["unsatisfiable"]))
        missed_bound = [a for a in r["ages_truth"] if a not in r["ages_got"]]
        if missed_bound and not diagnoses_only:
            flags.append("age bound missing:" + ",".join(missed_bound))
        if r["n_dx_got"] > 3 * max(r["n_dx_truth"], 1):
            flags.append("dx over-generated")
        gene_age = (f"{'-':>9}{'-':>8}" if diagnoses_only
                    else f"{r['gene_f1']:>9.2f}{r['age_f1']:>8.2f}")
        print(f"{r['nct_id']:<19}{r['registry']:<5}{r['dx_f1']:>7.2f}{r['dx_p']:>7.2f}{r['dx_r']:>7.2f}"
              f"{r['pop_p']:>7.2f}{r['pop_r']:>7.2f}{gene_age}"
              f"{r['n_dx_got']:>4}/{r['n_dx_truth']:<2}  {' '.join(flags)}")
    if ok:
        means = registry_means(rows)
        print("-" * width)
        for name in ("all",) + REGISTRIES:
            if name not in means:
                continue
            m = means[name]
            gene_age = (f"{'-':>9}{'-':>8}" if diagnoses_only
                        else f"{m['gene_f1']:>9.2f}{m['age_f1']:>8.2f}")
            print(f"{'MEAN':<19}{name:<5}{m['dx_f1']:>7.2f}{m['dx_p']:>7.2f}{m['dx_r']:>7.2f}"
                  f"{m['pop_p']:>7.2f}{m['pop_r']:>7.2f}{gene_age}{m['n']:>6} trials")
        print()
        for name in ("all",) + REGISTRIES:
            if name in means:
                m = means[name]
                print(f"exactly right ({name}): {m['exact_dx']} by name, "
                      f"{m['exact_pop']} by population, of {m['n']}")
        print(f"\nscored {len(ok)}/{len(rows)} trials")
        bad = [r['nct_id'] for r in ok if r['unsatisfiable']]
        if bad:
            print(f"unsatisfiable trees: {len(bad)}  {bad}")
    print("\nPer-trial detail is in the JSON report; read pop_missed and pop_extra "
          "before drawing a conclusion from the means.")


def write_conditions_baseline(ids, out_dir):
    """
    The diagnoses the pipeline reads from a trial's own conditions, written as
    minimal CTML so the ordinary scorer can read them.

    This is the deterministic half of the diagnosis path: the seed
    `seed_and_map_diagnosis` hands the model as a floor, and the
    `_SOLID_`/`_LIQUID_` rule for trials whose conditions name no Oncotree
    term. What the model adds on top is exactly the gap between this and a
    full run, so the two together separate a lookup regression from a model
    one - and this half needs no GPU and has no run-to-run variance.

    Both registries go through the same seed_and_map_diagnosis and the same
    basket fallback; only where the conditions are read from differs (see
    conditions_of). That is also what src/ctis.map_ctis_to_ctml does, since
    CTIS registers no keywords or titles for the NCT path's later fallbacks.
    """
    from loguru import logger
    logger.remove()
    import src.clinical_trials_gov as ctg
    for nct in ids:
        with open(f"{CACHE_DIRS[registry_of(nct)]}/{nct}.json") as handle:
            record = json.load(handle)
        conditions = conditions_of(nct, record)
        # The pipeline's own function with no eligibility text, so the model
        # is never called: whatever the seed and basket rules decide is exactly
        # what reaches the full run as its floor.
        diagnoses, _ = ctg.seed_and_map_diagnosis(nct, conditions, "")
        if not diagnoses:
            diagnoses = sorted(ctg.basket_wildcards(conditions, nct))
        doc = {"nct_id": nct, "treatment_list": {"step": [{"match": [
            {"or": [{"clinical": {"oncotree_primary_diagnosis": d}} for d in diagnoses]}]}]}}
        with open(f"{out_dir}/{nct}.yaml", "w") as handle:
            yaml.safe_dump(doc, handle, sort_keys=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="bench/output")
    ap.add_argument("--truth", default=TRUTH_DIR)
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", default="bench/report.json")
    ap.add_argument("--conditions-only", action="store_true",
                    help="diagnoses from the registry's condition list only; no model, no network")
    ap.add_argument("--source", choices=("all",) + REGISTRIES, default="all",
                    help="which registry's curated trials to run and score (default: all)")
    args = ap.parse_args()
    if args.conditions_only and args.out == "bench/output":
        args.out = "bench/output-conditions"

    ids = trial_ids(args.truth, args.source)
    if args.limit:
        ids = ids[:args.limit]
    os.makedirs(args.out, exist_ok=True)

    timings = {}
    if args.conditions_only:
        write_conditions_baseline(ids, args.out)
    elif not args.score_only:
        from loguru import logger
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
        import src.trial_map_manager as tmm
        print(f"platform={config.LLM_PLATFORM}  model={config.LLM_AI_MODEL}")
        print(f"mapping {len(ids)} trials -> {args.out}\n")
        mgr = tmm.TrialMapManager()
        for n, nct in enumerate(ids, 1):
            t0 = time.time()
            try:
                ok = map_trial(mgr, nct, args.out)
                status = "ok" if ok else "FAILED"
            except Exception as e:
                status = f"CRASH {type(e).__name__}: {str(e)[:60]}"
            timings[nct] = time.time() - t0
            print(f"  [{n}/{len(ids)}] {nct}  {status}  ({timings[nct]:.0f}s)")

    rows, agg = score(args.truth, args.out, ids)
    for r in rows:
        r["seconds"] = round(timings.get(r["nct_id"], 0), 1)
    report(rows, agg, diagnoses_only=args.conditions_only)
    with open(args.json, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    print(f"report written to {args.json}")


if __name__ == "__main__":
    main()
