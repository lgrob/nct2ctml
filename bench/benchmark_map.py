"""
Benchmark the automated `map` stage against hand-curated CTML.

ctml/reviewed/NCT*.yaml are curated by a human and verified end-to-end in
MatchMiner, so they serve as the answer key. This runs the pipeline over the
same trials and scores the result, so "is the LLM good enough to curate?" is
answered with numbers instead of impressions.

Scoring is deliberately blunt and reported alongside the raw sets, because no
single number decides this - a reviewer needs to see what the model actually
said. Three dimensions:

  diagnoses  Oncotree terms, exact set comparison (precision / recall / F1)
  genes      hugo_symbol values, exact set comparison
  structure  does the tree contain a gene asserted both present and absent -
             the unsatisfiable shape that matches zero patients

Usage:
    python -m bench.benchmark_map                 # run the pipeline, then score
    python -m bench.benchmark_map --score-only    # score an existing output dir
    python -m bench.benchmark_map --out DIR       # where mapped CTML goes
    python -m bench.benchmark_map --limit N       # first N trials only
"""
import argparse, json, os, sys, time, yaml
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
                ages.add(str(c["age_numerical"]).strip())
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
        gp, gr, gf = prf(o["genes"], t["genes"])
        uns = unsatisfiable(o["matches"])
        rows.append({
            "nct_id": nct, "status": "ok",
            "dx_p": dp, "dx_r": dr, "dx_f1": df,
            "gene_p": gp, "gene_r": gr, "gene_f1": gf,
            "n_dx_truth": len(t["diagnoses"]), "n_dx_got": len(o["diagnoses"]),
            "genes_truth": sorted(t["genes"]), "genes_got": sorted(o["genes"]),
            "dx_missed": sorted(t["diagnoses"] - o["diagnoses"])[:6],
            "dx_spurious": sorted(o["diagnoses"] - t["diagnoses"])[:6],
            "age_truth": t["age_label"], "age_got": o["age_label"],
            "unsatisfiable": sorted(uns),
        })
        for k in ("dx_f1", "gene_f1", "dx_p", "dx_r", "gene_p", "gene_r"):
            agg[k].append(rows[-1][k])
    return rows, agg


def report(rows, agg):
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\n{'trial':<14}{'dx F1':>7}{'dx P':>7}{'dx R':>7}{'gene F1':>9}"
          f"{'#dx':>6}{'  age':>8}  flags")
    print("-" * 78)
    for r in rows:
        if r["status"] != "ok":
            print(f"{r['nct_id']:<14}{r['status']}")
            continue
        flags = []
        if r["unsatisfiable"]:
            flags.append("UNSATISFIABLE:" + ",".join(r["unsatisfiable"]))
        if r["age_truth"] != r["age_got"]:
            flags.append(f"age {r['age_got']}!={r['age_truth']}")
        if r["n_dx_got"] > 3 * max(r["n_dx_truth"], 1):
            flags.append("dx over-generated")
        print(f"{r['nct_id']:<14}{r['dx_f1']:>7.2f}{r['dx_p']:>7.2f}{r['dx_r']:>7.2f}"
              f"{r['gene_f1']:>9.2f}{r['n_dx_got']:>3}/{r['n_dx_truth']:<2}"
              f"{str(r['age_got'])[:7]:>8}  {' '.join(flags)}")
    if ok:
        print("-" * 78)
        print(f"{'MEAN':<14}{sum(agg['dx_f1'])/len(ok):>7.2f}"
              f"{sum(agg['dx_p'])/len(ok):>7.2f}{sum(agg['dx_r'])/len(ok):>7.2f}"
              f"{sum(agg['gene_f1'])/len(ok):>9.2f}")
        print(f"\nscored {len(ok)}/{len(rows)} trials")
        bad = [r['nct_id'] for r in ok if r['unsatisfiable']]
        if bad:
            print(f"unsatisfiable trees: {len(bad)}  {bad}")
    print("\nPer-trial detail is in the JSON report; read the missed and spurious "
          "diagnosis lists before drawing a conclusion from the means.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="bench/output")
    ap.add_argument("--truth", default=TRUTH_DIR)
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", default="bench/report.json")
    args = ap.parse_args()

    ids = sorted(f[:-5] for f in os.listdir(args.truth)
                 if f.startswith("NCT") and f.endswith(".yaml"))
    if args.limit:
        ids = ids[:args.limit]
    os.makedirs(args.out, exist_ok=True)

    timings = {}
    if not args.score_only:
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
    report(rows, agg)
    with open(args.json, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    print(f"report written to {args.json}")


if __name__ == "__main__":
    main()
