"""
Review helper: put the evidence for every flag next to the flag, and make
accepting a reviewed trial a checked, logged step.

A trial lands in ctml/needs-review/ with one or more flags written beside
the item they concern (gene_unsupported, diagnosis_off_list,
protein_change_unverified, fusion_partner_unverified) or with no diagnosis
at all. Deciding each flag means finding the matching sentence in the
eligibility text. This module does that lookup deterministically, with the
same reference data the mapper uses, and writes one HTML sheet per trial:

- every flag, what it means, the text passages that mention the item
  (aliases, translocation notation and British spelling included), and the
  edit that resolves it;
- every diagnosis marked "named in text", "parent named in text" or "not
  named". On the stage-2 runs 82% of named diagnoses were correct, and most
  correct diagnoses are subtypes of a named parent, so the unnamed ones
  are where to look first;
- protein changes with the residue the reference protein actually carries;
- the eligibility text with every mention highlighted.

The sheet only reads. The curator edits the YAML in ctml/needs-review/ and
then runs `accept`, which refuses a file that still carries a flag, has no
diagnosis, names a gene or diagnosis that is not in the reference data, or
has a protein change that fails its reference check. On success it stamps
curated_on, moves the file to ctml/reviewed/ (the index layer that wins),
and appends one line to ctml/review_log.tsv: who, when, which flags were
resolved, and the file's SHA-256.

    python -m utils.review_helper queue                   # the queue, with reasons
    python -m utils.review_helper sheets                  # HTML sheets for the whole queue
    python -m utils.review_helper sheets NCT05843253      # ... or for named trials
    python -m utils.review_helper audit --n 60            # random mapped trials for roadmap 3.4
    python -m utils.review_helper check NCT05843253       # what accept would refuse, without moving
    python -m utils.review_helper accept NCT05843253 --reviewer lgrob [--note "..."]
    python -m utils.review_helper exclude NCT05843253 --reviewer lgrob --reason "adult-only, not oncology"

Sheets go to review_sheets/ (git-ignored); open review_sheets/index.html.
"""

import argparse
import csv
import datetime
import os
import sys

import yaml
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.text_rules as text_rules
import utils.review.common as common
import utils.review.evidence as evidence
import utils.review.gate as gate
import utils.review.maintenance as maintenance
import utils.review.sheets as sheets


def _parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("queue")
    s = sub.add_parser("sheets")
    s.add_argument("trials", nargs="*")
    a = sub.add_parser("audit")
    a.add_argument("--n", type=int, default=60)
    a.add_argument("--seed", type=int, default=20260925)
    c = sub.add_parser("check")
    c.add_argument("trial")
    ac = sub.add_parser("accept")
    ac.add_argument("trial")
    ac.add_argument("--reviewer", required=True)
    ac.add_argument("--note", default="")
    ac.add_argument("--replace", action="store_true")
    fx = sub.add_parser(
        "flag-exclusions", help="flag diagnoses named only in exclusion criteria in existing CTML"
    )
    fx.add_argument(
        "--apply", action="store_true", help="write the flag and move mapped trials to review"
    )
    sub.add_parser(
        "clear-stale-gene-flags",
        help="drop gene_unsupported where a single-arm trial names the gene",
    ).add_argument("--apply", action="store_true")
    sub.add_parser(
        "fix-all-lineage", help="add T-ALL where a trial names ALL without lineage"
    ).add_argument("--apply", action="store_true")
    sub.add_parser(
        "resolve-remap-drops", help="clear re-map drops named only in the exclusions"
    ).add_argument("--apply", action="store_true")
    sub.add_parser(
        "fix-genomic-notation", help="H3C3 beside H3C2; rearranged genes as Structural Variation"
    ).add_argument("--apply", action="store_true")
    fs = sub.add_parser(
        "flag-gene-status", help="genes required although the text says absent or irrelevant"
    )
    fs.add_argument(
        "--apply", action="store_true", help="write the flag and move mapped trials to review"
    )
    fg = sub.add_parser(
        "flag-unsupported-genes", help="re-run the unsupported-gene check on existing CTML"
    )
    fg.add_argument(
        "--apply", action="store_true", help="write the flag and move mapped trials to review"
    )
    sub.add_parser(
        "fix-age-operator", help="upper age bound '<=N' rewritten as '<N' (audit defect A)"
    ).add_argument("--apply", action="store_true")
    fa = sub.add_parser(
        "flag-age-units", help="registry age in days/weeks/months where the text says years"
    )
    fa.add_argument(
        "--apply", action="store_true", help="write the flag and move mapped trials to review"
    )
    fd = sub.add_parser(
        "flag-diagnosis-seed", help="basket on a specialty word; B-lineage on a T-lineage trial"
    )
    fd.add_argument(
        "--apply", action="store_true", help="write the flag and move mapped trials to review"
    )
    sub.add_parser(
        "audit-summary",
        help="curator-confirmed error rates from the audit-confirmation page (utils/review/audit_confirm.py)",
    )
    ex = sub.add_parser("exclude")
    ex.add_argument("trial")
    ex.add_argument("--reviewer", required=True)
    ex.add_argument("--reason", required=True)
    return ap


def _cmd_queue(args):
    ref = text_rules.Reference()
    for tid in gate._queue_ids():
        an = evidence.analyse(tid, ref)
        print(f"{tid}\t{','.join(an['flags'])}\t{an['title'][:80]}")


def _cmd_sheets(args):
    rows = sheets.write_sheets(
        args.trials or gate._queue_ids(),
        "Review queue" if not args.trials else "Selected trials",
    )
    print(f"{len(rows)} sheets in {common.SHEET_DIR}/ - open {common.SHEET_DIR}/index.html")


def _cmd_audit(args):
    ids, pool = gate.audit_sample(args.n, args.seed)
    out = f"ctml/audit_{datetime.date.today():%Y-%m-%d}.tsv"
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["trial_id", "verdict", "error_type", "note"])
        for t in ids:
            w.writerow([t, "", "", ""])
    sheets.write_sheets(
        ids,
        f"Audit sample: {len(ids)} of {pool} mapped trials (seed {args.seed})",
        out_dir=os.path.join(common.SHEET_DIR, "audit"),
    )
    print(
        f"{len(ids)} of {pool} mapped trials -> {out}; sheets in {common.SHEET_DIR}/audit/index.html"
    )


def _cmd_check(args):
    path, layer = common._layer_of(args.trial)
    raw = open(path).read()
    found = gate.problems(yaml.safe_load(raw), raw)
    print(
        f"{args.trial} ({layer}): "
        + ("ready to accept" if not found else "\n  - " + "\n  - ".join(found))
    )


def _cmd_accept(args):
    print(
        f"accepted -> {gate.accept(args.trial, args.reviewer, args.note, args.replace)}; logged in {common.LOG_FILE}"
    )


def _cmd_flag_exclusions(args):
    found = maintenance.flag_exclusions(apply=args.apply)
    for t, layer, hit in found:
        print(f"{t}\t{layer}\t{'; '.join(hit)}")
    moved = sum(1 for _, layer, _ in found if layer == "mapped")
    print(
        f"{len(found)} trials ({moved} mapped)"
        + (
            " flagged; mapped ones moved to the review queue"
            if args.apply
            else " would be flagged; run with --apply to write"
        )
    )


def _cmd_clear_stale_gene_flags(args):
    found = maintenance.clear_stale_gene_flags(apply=args.apply)
    for t, genes, moved in found:
        print(f"{t}\t{','.join(genes)}\t{'-> mapped' if moved else 'stays in review'}")
    print(
        f"{len(found)} trials, {sum(len(g) for _, g, _ in found)} flags"
        + (" cleared" if args.apply else " would be cleared; --apply to write")
    )


def _cmd_fix_all_lineage(args):
    found = maintenance.fix_all_lineage(apply=args.apply)
    for t, layer, n in found:
        print(f"{t}\t{layer}\t{n} B-ALL node(s) given a T-ALL alternative")
    print(
        f"{len(found)} trials"
        + (" updated" if args.apply else " would be updated; --apply to write")
    )


def _cmd_resolve_remap_drops(args):
    found = maintenance.resolve_remap_drops(apply=args.apply)
    for t, ok, left, moved, ev in found:
        print(
            f"{t}\tresolved {len(ok)}, left {len(left)}\t{'-> mapped' if moved else 'stays in review'}"
        )
        for e in ev:
            print(f"    {e}")
    print(
        f"{len(found)} trials, {sum(len(x[1]) for x in found)} drops"
        + (" resolved" if args.apply else " would be resolved; --apply to write")
    )


def _cmd_fix_genomic_notation(args):
    found = maintenance.fix_genomic_notation(apply=args.apply)
    for t, layer, n, rearr in found:
        print(f"{t}\t{layer}\tH3C3 x{n}\trearranged: {','.join(rearr) or '-'}")
    print(
        f"{len(found)} trials"
        + (" updated" if args.apply else " would be updated; --apply to write")
    )


def _cmd_flag_gene_status(args):
    found = maintenance.flag_gene_status(apply=args.apply)
    for t, layer, hit, action in found:
        print(
            f"{t}\t{layer}\t{action}\t"
            + " | ".join(f"{g}: {frag}" for g, frag in sorted(hit.items()))
        )
    moved = sum(1 for *_, a in found if a == "moved to review")
    print(
        f"{len(found)} trials ({moved} mapped)"
        + (
            " flagged; mapped ones moved to the review queue"
            if args.apply
            else " would be flagged; run with --apply to write"
        )
    )


def _cmd_flag_unsupported_genes(args):
    found = maintenance.flag_unsupported_genes(apply=args.apply)
    for t, layer, genes, action in found:
        print(f"{t}\t{layer}\t{action}\t{'; '.join(genes)}")
    moved = sum(1 for _, layer, _, a in found if a == "moved to review")
    print(
        f"{len(found)} trials ({moved} mapped would move to review)"
        if not args.apply
        else f"{len(found)} trials flagged; {moved} mapped ones moved to the review queue"
    )


def _cmd_fix_age_operator(args):
    found = maintenance.fix_age_operator(apply=args.apply)
    for t, layer, changes in found:
        print(f"{t}\t{layer}\t" + ", ".join(f"{o} -> {n}" for o, n in changes))
    print(
        f"{len(found)} trials, {sum(len(c) for *_, c in found)} bounds"
        + (" rewritten" if args.apply else " would be rewritten; --apply to write")
    )


def _cmd_flag_age_units(args):
    found = maintenance.flag_age_units(apply=args.apply)
    for t, layer, reason, action in found:
        print(f"{t}\t{layer}\t{action}\t{reason}")
    moved = sum(1 for *_, a in found if a == "moved to review")
    print(
        f"{len(found)} trials ({moved} mapped)"
        + (
            " flagged; mapped ones moved to the review queue"
            if args.apply
            else " would be flagged; run with --apply to write"
        )
    )


def _cmd_flag_diagnosis_seed(args):
    found = maintenance.flag_diagnosis_seed(apply=args.apply)
    for t, layer, reason, action in found:
        print(f"{t}\t{layer}\t{action}\t{reason}")
    moved = sum(1 for *_, a in found if a == "moved to review")
    print(
        f"{len(found)} trials ({moved} mapped)"
        + (
            " flagged; mapped ones moved to the review queue"
            if args.apply
            else " would be flagged; run with --apply to write"
        )
    )


def _cmd_audit_summary(args):
    import utils.review.audit_confirm as audit_confirm

    print(audit_confirm.summary_text())


def _cmd_exclude(args):
    layers = gate.exclude(args.trial, args.reviewer, args.reason)
    print(
        f"{args.trial} excluded (ref/scope_overrides.tsv; logged in {common.LOG_FILE}); "
        f"its copies in {', '.join(layers) or 'no layer'} are left in place and dropped at the next index build"
    )


COMMANDS = {
    "queue": _cmd_queue,
    "sheets": _cmd_sheets,
    "audit": _cmd_audit,
    "check": _cmd_check,
    "accept": _cmd_accept,
    "flag-exclusions": _cmd_flag_exclusions,
    "clear-stale-gene-flags": _cmd_clear_stale_gene_flags,
    "fix-all-lineage": _cmd_fix_all_lineage,
    "resolve-remap-drops": _cmd_resolve_remap_drops,
    "fix-genomic-notation": _cmd_fix_genomic_notation,
    "flag-gene-status": _cmd_flag_gene_status,
    "flag-unsupported-genes": _cmd_flag_unsupported_genes,
    "fix-age-operator": _cmd_fix_age_operator,
    "flag-age-units": _cmd_flag_age_units,
    "flag-diagnosis-seed": _cmd_flag_diagnosis_seed,
    "exclude": _cmd_exclude,
    "audit-summary": _cmd_audit_summary,
}


def main(argv=None):
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    args = _parser().parse_args(argv)
    COMMANDS[args.cmd](args)


if __name__ == "__main__":
    main()
