"""
Benchmark the automated `map` stage against hand-curated CTML.

ctml/reviewed/NCT*.yaml are curated by a human and verified end-to-end in
MatchMiner, so they serve as the answer key. This runs the pipeline over the
same trials and scores the result, so "is the LLM good enough to curate?" is
answered with numbers instead of impressions.

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
"""
import argparse, json, os, sys, time, yaml
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.build_trial_index import diagnosis_population

TRUTH_DIR = "ctml/reviewed"
CACHE_DIR = "cache/nct"


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
    """Genes asserted both present and absent inside the same AND branch."""
    out = set()

    def check(node):
        if isinstance(node, dict):
            if "and" in node and isinstance(node["and"], list):
                pos, neg = set(), set()
                for child in node["and"]:
                    for g in walk(child, "genomic"):
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
            rows.append({"nct_id": nct, "status": "MISSING OUTPUT"})
            continue
        t, o = facts(yaml.safe_load(open(tp))), facts(yaml.safe_load(open(op)))
        dp, dr, df = prf(o["diagnoses"], t["diagnoses"])
        pp, pr, pf, reached, wanted = population_prf(o["diagnoses"], t["diagnoses"])
        gp, gr, gf = prf(o["genes"], t["genes"])
        uns = unsatisfiable(o["matches"])
        ap_, ar_, af_ = prf(o["ages"], t["ages"])
        rows.append({
            "nct_id": nct, "status": "ok",
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


def report(rows, agg, diagnoses_only=False):
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\n{'trial':<14}{'dx F1':>7}{'dx P':>7}{'dx R':>7}{'pop P':>7}{'pop R':>7}"
          f"{'gene F1':>9}{'age F1':>8}{'#dx':>6}  flags")
    print("-" * 96)
    for r in rows:
        if r["status"] != "ok":
            print(f"{r['nct_id']:<14}{r['status']}")
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
        print(f"{r['nct_id']:<14}{r['dx_f1']:>7.2f}{r['dx_p']:>7.2f}{r['dx_r']:>7.2f}"
              f"{r['pop_p']:>7.2f}{r['pop_r']:>7.2f}{gene_age}"
              f"{r['n_dx_got']:>4}/{r['n_dx_truth']:<2}  {' '.join(flags)}")
    if ok:
        mean = lambda k: sum(agg[k]) / len(ok)
        gene_age = (f"{'-':>9}{'-':>8}" if diagnoses_only
                    else f"{mean('gene_f1'):>9.2f}{mean('age_f1'):>8.2f}")
        print("-" * 96)
        print(f"{'MEAN':<14}{mean('dx_f1'):>7.2f}{mean('dx_p'):>7.2f}{mean('dx_r'):>7.2f}"
              f"{mean('pop_p'):>7.2f}{mean('pop_r'):>7.2f}{gene_age}")
        exact = lambda k: sum(1 for r in ok if r[k] == 1.0)
        print(f"\nexactly right: {exact('dx_f1')} by name, {exact('pop_f1')} by population")
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
    """
    from loguru import logger
    logger.remove()
    import src.clinical_trials_gov as ctg
    import utils.reference_validation as rv
    for nct in ids:
        with open(f"{CACHE_DIR}/{nct}.json") as handle:
            record = json.load(handle)
        conditions = (record.get("protocolSection", {}).get("conditionsModule", {})
                      .get("conditions", []))
        diagnoses = rv.diagnoses_from_conditions(conditions, nct)
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
                    help="diagnoses from conditionsModule only; no model, no network")
    args = ap.parse_args()
    if args.conditions_only and args.out == "bench/output":
        args.out = "bench/output-conditions"

    ids = sorted(f[:-5] for f in os.listdir(args.truth)
                 if f.startswith("NCT") and f.endswith(".yaml"))
    if args.limit:
        ids = ids[:args.limit]
    os.makedirs(args.out, exist_ok=True)

    timings = {}
    if args.conditions_only:
        write_conditions_baseline(ids, args.out)
    elif not args.score_only:
        import config
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
                ok = mgr.map_single_trial(nct, CACHE_DIR, args.out)
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
