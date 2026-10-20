"""
Does a second reader's disagreement point at the errors?

utils/two_readers.py flags a trial when two independent mappings reach
different patients. That is only worth a curator's time if the flagged trials
are where the errors are. Two measurements:

    python -m bench.two_readers_measure benchmark --a DIR --b DIR
    python -m bench.two_readers_measure audit --primary DIR|release.tar.gz --second DIR

**benchmark** uses the curated key (ctml/reviewed) as the truth. Each
reader's mapping is compared with the key by the same comparator: `narrows`
against the key means the mapping loses patients, `widens` that it
over-matches. Then: of the trials where a reader loses patients, how many does
the A-B disagreement flag (sensitivity); how many correct trials it flags
anyway (false alarms); and what a union of the two readers' diagnoses would
score.

**audit** uses the third audit's verdicts (ctml/audit_2026-10-03.tsv), read
on trials the pipeline was not tuned on. `--primary` is the mapping the audit
judged - the release archive itself, whose inputs/cache/ctml it reads - and
`--second` the second reader's output.

Every count is against a key or a verdict, never against another model's
opinion. Nothing here writes outside --tsv.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import tarfile
import tempfile
from collections import Counter
from typing import Any

from src.text_rules import collect
from utils import two_readers as tr


def _load(path: str) -> dict | None:
    return tr._read(path)


def _dir_from(source: str) -> str:
    """A directory of mapped CTML, extracting a release archive if given one."""
    if os.path.isdir(source):
        return source
    if not tarfile.is_tarfile(source):
        raise SystemExit(f"{source}: neither a directory nor a release archive")
    out = tempfile.mkdtemp(prefix="two_readers_")
    with tarfile.open(source) as archive:
        for member in archive.getmembers():
            parts = member.name.split("/")
            # <tag>/inputs/cache/ctml/<id>.yaml and <tag>/inputs/ctml/needs-review/<id>.yaml
            if member.isfile() and member.name.endswith(".yaml") and "inputs" in parts:
                sub = "needs-review" if "needs-review" in parts else ""
                target = os.path.join(out, sub, parts[-1])
                os.makedirs(os.path.dirname(target), exist_ok=True)
                handle = archive.extractfile(member)
                if handle is not None:
                    with open(target, "wb") as dest:
                        dest.write(handle.read())
    return out


def _population(doc: dict) -> set[str]:
    included, excluded = tr._diagnosis_terms(collect(doc))
    return tr._population(included, excluded)


def _prf(got: set[str], want: set[str]) -> tuple[float, float]:
    if not got and not want:
        return 1.0, 1.0
    hit = len(got & want)
    return (hit / len(got) if got else 0.0), (hit / len(want) if want else 0.0)


def _pct(k: int, n: int) -> str:
    return f"{k}/{n}" + (f" ({100 * k / n:.0f}%)" if n else "")


# ---------------------------------------------------------------- benchmark
def benchmark(a_dir: str, b_dir: str, truth_dir: str, tsv: str | None) -> None:
    a, b = tr._trials(a_dir), tr._trials(b_dir)
    truth = {
        f[: -len(".yaml")]: os.path.join(truth_dir, f)
        for f in os.listdir(truth_dir)
        if f.endswith(".yaml")
    }
    ids = sorted(set(a) & set(b) & set(truth))
    rows: list[dict[str, Any]] = []
    for t in ids:
        da, db, dk = _load(a[t]), _load(b[t]), _load(truth[t])
        if da is None or db is None or dk is None:
            continue
        pair = tr.compare(t, da, db)
        vs_a, vs_b = tr.compare(t, da, dk), tr.compare(t, db, dk)
        pop_k, pop_a, pop_b = _population(dk), _population(da), _population(db)
        rows.append(
            {
                "trial_id": t,
                "flag": "agree" if pair.agree else ("narrows" if pair.narrows else "widens"),
                "a_vs_key": "correct" if vs_a.agree else ("loses" if vs_a.narrows else "over"),
                "b_vs_key": "correct" if vs_b.agree else ("loses" if vs_b.narrows else "over"),
                "a_dx": _prf(pop_a, pop_k),
                "b_dx": _prf(pop_b, pop_k),
                "union_dx": _prf(pop_a | pop_b, pop_k),
                "differences": " | ".join(str(d) for d in pair.differences),
            }
        )
    n = len(rows)
    flagged = [r for r in rows if r["flag"] != "agree"]
    print(f"trials in A, B and the key: {n}")
    print(
        f"A and B disagree on {_pct(len(flagged), n)}, narrowing on "
        f"{_pct(sum(r['flag'] == 'narrows' for r in rows), n)}"
    )
    for side, label in (("a_vs_key", "A"), ("b_vs_key", "B")):
        loses = [r for r in rows if r[side] == "loses"]
        over = [r for r in rows if r[side] == "over"]
        correct = [r for r in rows if r[side] == "correct"]
        print(
            f"\nreader {label} against the key: {len(loses)} lose patients, "
            f"{len(over)} over-match only, {len(correct)} correct"
        )
        print(
            f"  losing trials flagged by the disagreement: "
            f"{_pct(sum(r['flag'] != 'agree' for r in loses), len(loses))}"
        )
        print(
            f"  over-matching trials flagged: "
            f"{_pct(sum(r['flag'] != 'agree' for r in over), len(over))}"
        )
        print(
            f"  correct trials flagged anyway: "
            f"{_pct(sum(r['flag'] != 'agree' for r in correct), len(correct))}"
        )
    either = [r for r in rows if "loses" in (r["a_vs_key"], r["b_vs_key"])]
    both = [r for r in rows if r["a_vs_key"] == r["b_vs_key"] == "loses"]
    print(
        f"\ntrials where either reader loses patients: {len(either)}; "
        f"both lose: {len(both)} - a shared error the disagreement cannot see"
    )
    print("\npopulation precision / recall, mean over trials:")
    for key, label in (("a_dx", "A"), ("b_dx", "B"), ("union_dx", "A or B")):
        p = statistics.mean(r[key][0] for r in rows) if rows else 0
        rc = statistics.mean(r[key][1] for r in rows) if rows else 0
        print(f"  {label:7s} {p:.3f} / {rc:.3f}")
    if tsv:
        _write(tsv, rows)


# ---------------------------------------------------------------- audit
def audit(primary: str, second_dir: str, sheet: str, tsv: str | None) -> None:
    primary_dir = _dir_from(primary)
    p, s = tr._trials(primary_dir), tr._trials(second_dir)
    with open(sheet, newline="", encoding="utf-8") as handle:
        verdicts = {r["trial_id"]: r for r in csv.DictReader(handle, delimiter="\t")}
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for t, v in sorted(verdicts.items()):
        if t not in p or t not in s:
            missing.append(t)
            continue
        dp, ds = _load(p[t]), _load(s[t])
        if dp is None or ds is None:
            missing.append(t)
            continue
        pair = tr.compare(t, dp, ds)
        effect = v["effect"] if v["verdict"] == "error" else v["verdict"]
        rows.append(
            {
                "trial_id": t,
                "verdict": effect,
                "flag": "agree" if pair.agree else ("narrows" if pair.narrows else "widens"),
                "cause": v.get("cause", ""),
                "differences": " | ".join(str(d) for d in pair.differences),
            }
        )
    print(
        f"audited trials with both mappings: {len(rows)} of {len(verdicts)}"
        + (
            f" (missing: {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''})"
            if missing
            else ""
        )
    )
    table = Counter((r["verdict"], r["flag"]) for r in rows)
    order = ("loses", "both", "over-match", "borderline", "correct")
    print(f"\n{'audit verdict':14s} {'n':>4s} {'flagged':>9s} {'narrows':>9s}")
    for verdict in order:
        n = sum(table[(verdict, f)] for f in ("agree", "narrows", "widens"))
        n_flagged = table[(verdict, "narrows")] + table[(verdict, "widens")]
        print(
            f"{verdict:14s} {n:4d} {_pct(n_flagged, n):>9s} {_pct(table[(verdict, 'narrows')], n):>9s}"
        )
    losing = [r for r in rows if r["verdict"] in ("loses", "both")]
    flagged = [r for r in rows if r["flag"] != "agree"]
    print(
        f"\nlosing trials flagged: {_pct(sum(r['flag'] != 'agree' for r in losing), len(losing))}"
    )
    print(
        f"flagged trials that are audit errors: "
        f"{_pct(sum(r['verdict'] in ('loses', 'both', 'over-match') for r in flagged), len(flagged))}"
    )
    print(f"review load: {_pct(len(flagged), len(rows))} of the audited trials")
    if tsv:
        _write(tsv, rows)


def _write(path: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nper-trial rows: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.two_readers_measure")
    sub = ap.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("benchmark", help="against the curated key")
    b.add_argument("--a", required=True, help="reader A's benchmark output directory")
    b.add_argument("--b", required=True, help="reader B's benchmark output directory")
    b.add_argument("--truth", default="ctml/reviewed")
    b.add_argument("--tsv")
    a = sub.add_parser("audit", help="against the third audit's verdicts")
    a.add_argument(
        "--primary", required=True, help="the audited mapping: a directory or release archive"
    )
    a.add_argument("--second", required=True, help="the second reader's output directory")
    a.add_argument("--sheet", default="ctml/audit_2026-10-03.tsv")
    a.add_argument("--tsv")
    args = ap.parse_args(argv)
    if args.mode == "benchmark":
        benchmark(args.a, args.b, args.truth, args.tsv)
    else:
        audit(args.primary, args.second, args.sheet, args.tsv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
