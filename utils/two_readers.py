"""
Two independent readers: compare two mappings of the same trial.

A trial is mapped twice, by models of different families, and the two CTML
documents are compared on what decides which patients a trial reaches: the
diagnosis population, the required and excluded genes, and the age window.
Where they agree the primary mapping stands. Where they disagree, the trial
is flagged `reader_disagreement` and goes to review.

Why a second model and not the same model twice: re-running one model at
temperature 0 measures its sampling noise, not whether its reading is right,
so agreement between two runs of it says little. Two model families make
independent errors where the text is hard for one of them.

What it cannot see: an error both readers share. On the 2026-09-30 benchmark
the trials both models failed identically were failures of the pipeline or
the answer key - the inclusion/exclusion splitter, the cohort rule, an alias
- which a second reader agrees with. The deterministic checks stay the
guard for those.

Comparison is on effect, not wording:

- Diagnoses are compared as the patients they reach (build_trial_index
  .diagnosis_population), with '!' exclusions taken out, so "Glioma" and its
  children, or a wildcard and its members, agree.
- Genes are compared as (symbol, base variant category, excluded or
  required). The OR/AND structure is not compared: this is a review trigger,
  not a verdict, and a difference in structure alone sends nothing to review.
- Ages are compared as the numeric window MatchMiner uses (< and <= alike).

Each difference has a direction from the primary reader's side, because the
primary mapping is what would be published:

- `narrows`: the primary shuts out patients the second admits - a diagnosis
  population only the second reaches, a gene requirement or exclusion only
  the primary has, a tighter age bound. The costly error: a patient who never
  sees a trial they qualify for.
- `widens`: the primary admits patients the second shuts out. Costs a
  clinician a manual rejection.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

from src.text_rules import collect
from utils.build_trial_index import _parse_age_bounds, diagnosis_population

NARROWS = "narrows"
WIDENS = "widens"

# Where a curator reads the result; also the key `accept` refuses while set.
FLAG = "reader_disagreement"


@dataclass
class Difference:
    """One way the two readers disagree on a trial."""

    dimension: str  # "diagnosis" | "gene" | "age"
    direction: str  # NARROWS | WIDENS, from the primary reader's side
    detail: str  # what a curator reads

    def __str__(self) -> str:
        return f"{self.dimension} {self.direction}: {self.detail}"


@dataclass
class Comparison:
    trial_id: str
    differences: list[Difference] = field(default_factory=list)

    @property
    def agree(self) -> bool:
        return not self.differences

    @property
    def narrows(self) -> bool:
        return any(d.direction == NARROWS for d in self.differences)

    def flag_text(self, second_reader: str) -> str:
        """The reader_disagreement value written to the primary CTML."""
        return f"{second_reader}: " + "; ".join(str(d) for d in self.differences)


# ------------------------------------------------------------- dimensions
def _diagnosis_terms(facts: dict[str, list]) -> tuple[set[str], set[str]]:
    included: set[str] = set()
    excluded: set[str] = set()
    for term in facts["diagnoses"]:
        term = str(term).strip().strip("'\"")
        if not term:
            continue
        if term.startswith("!"):
            excluded.add(term[1:].strip())
        else:
            included.add(term)
    return included, excluded


def _population(included: set[str], excluded: set[str]) -> set[str]:
    return diagnosis_population(included) - (diagnosis_population(excluded) if excluded else set())


def _terms_reaching(terms: set[str], beyond: set[str], excluded: set[str]) -> list[str]:
    """The terms whose patients are not all inside `beyond`, for display."""
    gone = diagnosis_population(excluded) if excluded else set()
    return sorted(t for t in terms if (diagnosis_population({t}) - gone) - beyond)


def _compare_diagnoses(a: dict, b: dict) -> list[Difference]:
    a_inc, a_exc = _diagnosis_terms(a)
    b_inc, b_exc = _diagnosis_terms(b)
    pop_a, pop_b = _population(a_inc, a_exc), _population(b_inc, b_exc)
    out = []
    if pop_b - pop_a:
        terms = _terms_reaching(b_inc, pop_a, b_exc)
        out.append(
            Difference(
                "diagnosis",
                NARROWS,
                f"only the second reader reaches {len(pop_b - pop_a)} patient code(s), "
                f"via {', '.join(terms[:6]) or 'its exclusions'}",
            )
        )
    if pop_a - pop_b:
        terms = _terms_reaching(a_inc, pop_b, a_exc)
        out.append(
            Difference(
                "diagnosis",
                WIDENS,
                f"only the primary reaches {len(pop_a - pop_b)} patient code(s), "
                f"via {', '.join(terms[:6]) or 'its exclusions'}",
            )
        )
    return out


def _gene_items(facts: dict[str, list]) -> set[tuple[str, str, bool]]:
    """(symbol, base category, excluded) for every genomic node."""
    items: set[tuple[str, str, bool]] = set()
    for g in facts["genomic"]:
        symbol = str(g.get("hugo_symbol") or "").strip()
        if not symbol:
            continue
        category = str(g.get("variant_category") or "")
        items.add((symbol, category.lstrip("!").strip().lower(), category.startswith("!")))
    return items


def _gene_label(item: tuple[str, str, bool]) -> str:
    symbol, category, excluded = item
    return f"{'!' if excluded else ''}{symbol} {category}".strip()


def _compare_genes(a: dict, b: dict) -> list[Difference]:
    ga, gb = _gene_items(a), _gene_items(b)
    out = []
    # A requirement or an exclusion only the primary has shuts patients out.
    if ga - gb:
        out.append(
            Difference(
                "gene",
                NARROWS,
                "only the primary has " + ", ".join(_gene_label(i) for i in sorted(ga - gb)),
            )
        )
    if gb - ga:
        out.append(
            Difference(
                "gene",
                WIDENS,
                "only the second reader has " + ", ".join(_gene_label(i) for i in sorted(gb - ga)),
            )
        )
    return out


def _bound(value: float | None) -> str:
    return "none" if value is None else f"{value:g}"


def _compare_ages(a: dict, b: dict) -> list[Difference]:
    lo_a, _, hi_a, _ = _parse_age_bounds(a["ages"])
    lo_b, _, hi_b, _ = _parse_age_bounds(b["ages"])
    out = []
    # None is unbounded; MatchMiner treats < and <= alike, so inclusivity is ignored.
    lower_tighter = lo_a is not None and (lo_b is None or lo_a > lo_b)
    upper_tighter = hi_a is not None and (hi_b is None or hi_a < hi_b)
    lower_looser = lo_b is not None and (lo_a is None or lo_a < lo_b)
    upper_looser = hi_b is not None and (hi_a is None or hi_a > hi_b)
    window = f"primary {_bound(lo_a)}-{_bound(hi_a)}, second {_bound(lo_b)}-{_bound(hi_b)}"
    if lower_tighter or upper_tighter:
        out.append(Difference("age", NARROWS, window))
    if lower_looser or upper_looser:
        out.append(Difference("age", WIDENS, window))
    return out


def compare(trial_id: str, primary: dict, second: dict) -> Comparison:
    """Compare two CTML documents for one trial."""
    a = collect(primary or {})
    b = collect(second or {})
    result = Comparison(trial_id)
    result.differences += _compare_diagnoses(a, b)
    result.differences += _compare_genes(a, b)
    result.differences += _compare_ages(a, b)
    return result


# ------------------------------------------------------------- reconcile
def _read(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            doc = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


def _trials(directory: str) -> dict[str, str]:
    """trial_id -> path, from a mapping output and its needs-review subfolder."""
    found: dict[str, str] = {}
    for sub in (directory, os.path.join(directory, "needs-review")):
        if not os.path.isdir(sub):
            continue
        for name in sorted(os.listdir(sub)):
            if name.endswith(".yaml"):
                found.setdefault(name[: -len(".yaml")], os.path.join(sub, name))
    return found


def _second_reader_name(second_dir: str, docs: list[dict]) -> str:
    """The second reader's model, from its provenance stamp, else its folder."""
    for doc in docs:
        llm = (((doc or {}).get("_provenance") or {}).get("llm")) or {}
        model = llm.get("model")
        if model:
            return str(model)
    return os.path.basename(os.path.normpath(second_dir))


def _flagged_text(raw: str, text: str) -> str:
    """
    The file with a top-level reader_disagreement line, by text append as in
    utils/review/maintenance, so curator comments and key order survive. A
    previous flag line is replaced rather than stacked.
    """
    kept = "".join(
        line for line in raw.splitlines(keepends=True) if not line.startswith(f"{FLAG}:")
    )
    return kept.rstrip("\n") + "\n" + yaml.safe_dump({FLAG: text}, allow_unicode=True, width=1000)


def _primary_copies(primary_dir: str, review_dir: str, reviewed_dir: str) -> dict[str, str]:
    """
    trial_id -> the primary file the index publishes for it.

    The review copy wins over the mapped one, as in the index, and a trial with
    a curated copy is left out: a curator's file is never second-guessed by a
    model comparison.
    """
    found: dict[str, str] = {}
    for directory in (primary_dir, review_dir):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(".yaml"):
                found[name[: -len(".yaml")]] = os.path.join(directory, name)
    if os.path.isdir(reviewed_dir):
        for name in os.listdir(reviewed_dir):
            found.pop(name[: -len(".yaml")] if name.endswith(".yaml") else name, None)
    return found


def reconcile(
    primary_dir: str,
    second_dir: str,
    review_dir: str,
    reviewed_dir: str = "ctml/reviewed",
    route: str = "narrows",
    apply: bool = False,
) -> list[dict[str, Any]]:
    """
    Compare every trial both readers mapped; with `apply`, flag the
    disagreeing ones and move them to `review_dir`.

    The primary side is what the index publishes: `primary_dir` and
    `review_dir`, the review copy winning, curated trials (`reviewed_dir`)
    left out. `route` is "narrows" (only a disagreement where the primary
    shuts patients out; the default, see config.TWO_READERS_ROUTE) or "any"
    (every disagreement goes to review).
    """
    primary = _primary_copies(primary_dir, review_dir, reviewed_dir)
    second = _trials(second_dir)
    shared = sorted(set(primary) & set(second))
    reader = _second_reader_name(second_dir, [_read(second[t]) or {} for t in shared[:5]])
    review_real = os.path.realpath(review_dir)
    rows: list[dict[str, Any]] = []
    for trial_id in shared:
        a, b = _read(primary[trial_id]), _read(second[trial_id])
        if a is None or b is None:
            rows.append({"trial_id": trial_id, "status": "unreadable"})
            continue
        result = compare(trial_id, a, b)
        routed = not result.agree and (route == "any" or result.narrows)
        src = primary[trial_id]
        in_review = os.path.realpath(os.path.dirname(src)) == review_real
        row: dict[str, Any] = {
            "trial_id": trial_id,
            "status": "agree" if result.agree else ("narrows" if result.narrows else "widens"),
            "routed": routed,
            "primary_file": src,
            "differences": " | ".join(str(d) for d in result.differences),
            "action": "",
        }
        if routed:
            if not apply:
                row["action"] = "would flag" + ("" if in_review else " and move to review")
            else:
                with open(src, encoding="utf-8") as handle:
                    raw = handle.read()
                target = src if in_review else os.path.join(review_dir, os.path.basename(src))
                os.makedirs(review_dir, exist_ok=True)
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(_flagged_text(raw, result.flag_text(reader)))
                if not in_review:
                    os.remove(src)
                row["action"] = "flagged" + ("" if in_review else ", moved to review")
        rows.append(row)
    for trial_id in sorted(set(primary) ^ set(second)):
        rows.append(
            {
                "trial_id": trial_id,
                "status": "primary only" if trial_id in primary else "second only",
            }
        )
    return rows


def _summary(rows: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    routed = sum(1 for row in rows if row.get("routed"))
    compared = sum(counts.get(k, 0) for k in ("agree", "narrows", "widens"))
    parts = [f"{compared} trials compared"]
    parts += [f"{counts.get(k, 0)} {k}" for k in ("agree", "narrows", "widens")]
    parts.append(f"{routed} to review")
    for k in ("primary only", "second only", "unreadable"):
        if counts.get(k):
            parts.append(f"{counts[k]} {k}")
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    import config

    ap = argparse.ArgumentParser(
        prog="python -m utils.two_readers",
        description="Compare two readers' mappings; flag and route the trials they disagree on.",
    )
    ap.add_argument("--primary", default=config.CTML_MAPPED_PATH, help="the published mapping")
    ap.add_argument("--second", required=True, help="the second reader's mapping (map --out DIR)")
    ap.add_argument("--review", default=config.CTML_REVIEW_PATH, help="where routed trials go")
    ap.add_argument(
        "--route",
        choices=("any", "narrows"),
        default=config.TWO_READERS_ROUTE,
        help="send every disagreement to review, or only those where the primary narrows",
    )
    ap.add_argument("--tsv", help="write one row per trial here")
    ap.add_argument("--apply", action="store_true", help="write the flags and move the files")
    args = ap.parse_args(argv)

    rows = reconcile(
        args.primary, args.second, args.review, config.CTML_REVIEWED_PATH, args.route, args.apply
    )
    if args.tsv:
        cols = ["trial_id", "status", "routed", "action", "differences", "primary_file"]
        with open(args.tsv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, cols, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    print(_summary(rows))
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply to flag and move.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
