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
import re
import sys

import yaml
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.text_rules as text_rules
import utils.reference_validation as rv
import utils.review.common as common
import utils.review.evidence as evidence
import utils.review.gate as gate
import utils.review.sheets as sheets

# --------------------------------------------------------------------- data


# ----------------------------------------------------------------- evidence


def flag_exclusions(apply=False):
    """
    Apply the diagnosis_excluded check to CTML already written (mapped and
    review layers; ctml/reviewed is never touched). Returns
    [(trial_id, layer, [diagnoses])]. With apply=True, the key is added and a
    mapped trial is moved to the review queue, as the mapper now does.
    """
    ref = text_rules._shared_reference()
    import utils.oncology_scope as scope

    out_of_scope = set(scope.load_report()) | {
        t for t, (dec, _) in scope.load_overrides().items() if dec == "skip"
    }
    found = []
    for d, layer in ((common.MAPPED_DIR, "mapped"), (common.REVIEW_DIR, "needs_review")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".yaml"):
                continue
            t = f[:-5]
            if t in out_of_scope:
                continue  # not in the index; no point queueing it
            if os.path.exists(os.path.join(common.REVIEWED_DIR, f)):
                continue  # a curated copy exists and is what the index publishes
            path = os.path.join(d, f)
            raw = open(path).read()
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict) or ctml.get("diagnosis_excluded"):
                continue
            try:
                inc, exc, data = evidence.eligibility_text(t)
            except (OSError, ValueError, KeyError):
                continue
            context = [
                str(ctml.get("long_title") or ""),
                str(ctml.get("short_title") or ""),
            ] + evidence._conditions(t, data)
            hit = text_rules.diagnoses_only_in_exclusions(
                text_rules.collect(ctml)["diagnoses"], inc, exc, context, ref
            )
            if not hit:
                continue
            found.append((t, layer, hit))
            if apply:
                target = os.path.join(common.REVIEW_DIR, f)
                if layer == "mapped" and os.path.exists(target):
                    continue  # a review copy exists and wins; leave both for the curator
                text = (
                    raw.rstrip("\n")
                    + "\n"
                    + yaml.safe_dump(
                        {"diagnosis_excluded": "; ".join(hit)}, allow_unicode=True, width=1000
                    )
                )
                os.makedirs(common.REVIEW_DIR, exist_ok=True)
                with open(target, "w") as fh:
                    fh.write(text)
                if layer == "mapped":
                    os.remove(path)
    return found


def clear_stale_gene_flags(apply=False):
    """
    Remove gene_unsupported from genes a single-arm trial does name, as the
    current scan and text check read it (e.g. "(IDH) 1/2", 2024-516896-34-00).
    With one arm the arm's criteria text is the trial's text, so such a flag
    is stale: it was set by an older scan. Multi-arm trials keep the flag,
    because the gene may belong to another arm (cohort-scope problem).
    Removes the line in place, so curator comments survive. A file left with
    no flag at all and no curator comment moves back to cache/ctml/.
    Returns [(trial_id, [genes], moved)].
    """
    import src.match_criteria_mapper as mcm
    import src.trial_criteria_to_genes as tg

    syn = rv.gene_synonym_mapping()
    out = []
    for f in sorted(os.listdir(common.REVIEW_DIR)):
        if not f.endswith(".yaml"):
            continue
        t, path = f[:-5], os.path.join(common.REVIEW_DIR, f)
        raw = open(path).read()
        ctml = yaml.safe_load(raw)
        if (
            not isinstance(ctml, dict)
            or len((ctml.get("treatment_list") or {}).get("step", [{}])[0].get("arm") or []) != 1
        ):
            continue
        flagged = {
            g.get("hugo_symbol")
            for g in text_rules._genomic_nodes(ctml.get("treatment_list"))
            if g.get("gene_unsupported")
        }
        if not flagged:
            continue
        try:
            inc, exc, data = evidence.eligibility_text(t)
        except (OSError, ValueError, KeyError):
            continue
        text = "\n".join([inc, exc] + list(evidence._arm_and_title_text(t, data)))
        scan = set(
            tg.TrialCriteriaToGenes(
                trial_criteria=text, synonym_to_symbol=syn
            ).extract_official_gene_symbols()
        )
        clear = sorted(g for g in flagged if g in scan or mcm._text_mentions_gene(text, g))
        if not clear:
            continue
        new, current = [], None
        for line in raw.split("\n"):
            m = re.match(r"^\s*(?:-\s+)?hugo_symbol:\s*'?([^'\s]+)'?\s*$", line)
            if m:
                current = m.group(1)
            elif re.match(r"^\s*-?\s*genomic:", line) or re.match(r"^\s*-\s", line):
                current = None
            if current in clear and line.strip().startswith("gene_unsupported:"):
                continue
            new.append(line)
        text_out = "\n".join(new)
        left = yaml.safe_load(text_out)
        moved = not gate.problems(left, text_out) and not re.search(r"^\s*#", text_out, re.M)
        out.append((t, clear, moved))
        if apply:
            if moved:
                with open(os.path.join(common.MAPPED_DIR, f), "w") as fh:
                    fh.write(text_out)
                os.remove(path)
            else:
                with open(path, "w") as fh:
                    fh.write(text_out)
    return out


def fix_genomic_notation(apply=False):
    """
    Existing output: H3C3 beside H3C2 (the H3 keyword map lacked it until
    2026-09-27), and a gene the text names only as rearranged becomes a
    Structural Variation (match_criteria_mapper.rearranged_as_structural).
    Mapped and review layers; reviewed and curator-edited files are skipped.
    Returns [(trial_id, layer, n_h3c3, [rearranged genes])].
    """
    import src.match_criteria_mapper as mcm
    import utils.oncology_scope as scope

    out_of_scope = set(scope.load_report()) | {
        t for t, (d, _) in scope.load_overrides().items() if d == "skip"
    }
    found = []
    for d, layer in ((common.MAPPED_DIR, "mapped"), (common.REVIEW_DIR, "needs_review")):
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.endswith(".yaml"):
                continue
            t, path = f[:-5], os.path.join(d, f)
            if (
                t in out_of_scope
                or os.path.exists(os.path.join(common.REVIEWED_DIR, f))
                or (layer == "mapped" and os.path.exists(os.path.join(common.REVIEW_DIR, f)))
            ):
                continue
            raw = open(path).read()
            if re.search(r"^\s*#", raw, re.M):
                continue
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict):
                continue
            n_h3 = text_rules.add_sibling_gene(ctml.get("treatment_list"), "H3C2", "H3C3")
            try:
                inc, exc, _ = evidence.eligibility_text(t)
            except (OSError, ValueError, KeyError):
                inc = exc = ""
            before = [
                (id(g), g.get("variant_category"))
                for g in text_rules._genomic_nodes(ctml.get("treatment_list"))
            ]
            nodes = list(text_rules._genomic_nodes(ctml.get("treatment_list")))
            mcm.rearranged_as_structural([{"genomic": g} for g in nodes], inc + "\n" + exc, t)
            rearr = sorted(
                {
                    g["hugo_symbol"]
                    for g, (_, vc) in zip(nodes, before, strict=True)
                    if g.get("variant_category") != vc
                }
            )
            if n_h3 or rearr:
                found.append((t, layer, n_h3, rearr))
                if apply:
                    with open(path, "w") as fh:
                        fh.write(yaml.dump(ctml, sort_keys=False))
    return found


def fix_all_lineage(apply=False):
    """Apply all_lineage_unspecified to CTML already written (mapped and review layers)."""
    import utils.oncology_scope as scope

    out_of_scope = set(scope.load_report()) | {
        t for t, (d, _) in scope.load_overrides().items() if d == "skip"
    }
    found = []
    for d, layer in ((common.MAPPED_DIR, "mapped"), (common.REVIEW_DIR, "needs_review")):
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.endswith(".yaml"):
                continue
            t, path = f[:-5], os.path.join(d, f)
            if (
                t in out_of_scope
                or os.path.exists(os.path.join(common.REVIEWED_DIR, f))
                or (layer == "mapped" and os.path.exists(os.path.join(common.REVIEW_DIR, f)))
            ):
                continue
            raw = open(path).read()
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict) or re.search(r"^\s*#", raw, re.M):
                continue  # curator-edited files are left to the curator
            try:
                inc, exc, data = evidence.eligibility_text(t)
            except (OSError, ValueError, KeyError):
                continue
            ctx = [str(c) for c in evidence._conditions(t, data)] + list(
                evidence._arm_and_title_text(t, data)
            )
            if not text_rules.all_lineage_unspecified(
                text_rules.collect(ctml)["diagnoses"], inc, exc, ctx
            ):
                continue
            n = text_rules.add_sibling_diagnosis(
                ctml.get("treatment_list"), text_rules.B_ALL, text_rules.T_ALL
            )
            found.append((t, layer, n))
            if apply and n:
                with open(path, "w") as fh:
                    fh.write(yaml.dump(ctml, sort_keys=False))
    return found


def resolve_remap_drops(apply=False):
    """
    Remove from remap_dropped_diagnoses every diagnosis named only in the
    exclusion criteria: the re-map was right to drop it (the same rule the
    re-map integration applies, re-run with today's diagnosis text terms).
    Rewrites only the flag line, so curator comments survive; a file left
    with no flag and no comment moves back to cache/ctml/.
    Returns [(trial_id, [resolved], [remaining], moved, evidence)].
    """
    ref = text_rules._shared_reference()
    out = []
    for f in sorted(os.listdir(common.REVIEW_DIR)):
        if not f.endswith(".yaml"):
            continue
        t, path = f[:-5], os.path.join(common.REVIEW_DIR, f)
        raw = open(path).read()
        ctml = yaml.safe_load(raw)
        dropped = common._as_set((ctml or {}).get("remap_dropped_diagnoses"))
        if not dropped:
            continue
        try:
            inc, exc, data = evidence.eligibility_text(t)
        except (OSError, ValueError, KeyError):
            continue
        ctx = [str(c) for c in evidence._conditions(t, data)] + list(
            evidence._arm_and_title_text(t, data)
        )
        ok = sorted(
            set(text_rules.diagnoses_only_in_exclusions(sorted(dropped), inc, exc, ctx, ref=ref))
        )
        # An exclusion scoped to part of the trial ("excluded from the
        # randomization part", a cohort or stratum) does not exclude the
        # patient from the trial (2023-505512-37-00, NCT05477589: MDS).
        ok = [
            x
            for x in ok
            if not any(
                re.search(
                    r"randomi[sz]|cohort|stratum|arm\s+[A-D1-4]\b|part\s+[A-D1-4I]\b",
                    exc[max(0, s - 250) : s],
                    re.I,
                )
                for s, _, _ in text_rules.find_mentions(exc, ref.dx_terms(x))
            )
        ]
        if not ok:
            continue
        left = sorted(dropped - set(ok))
        ev = []
        for x in ok:
            s, e, _ = text_rules.find_mentions(exc, ref.dx_terms(x))[0]
            ev.append(f"{x}: ...{' '.join(exc[max(0, s - 50) : e + 20].split())}...")
        lines = raw.split("\n")
        k = next(i for i, line in enumerate(lines) if line.startswith("remap_dropped_diagnoses:"))
        if left:
            lines[k] = yaml.safe_dump(
                {"remap_dropped_diagnoses": "; ".join(left)}, width=1000
            ).rstrip("\n")
        else:
            del lines[k]
        text_out = "\n".join(lines)
        moved = (
            not left
            and not gate.problems(yaml.safe_load(text_out), text_out)
            and not re.search(r"^\s*#", text_out, re.M)
        )
        out.append((t, ok, left, moved, ev))
        if apply:
            with open(os.path.join(common.MAPPED_DIR, f) if moved else path, "w") as fh:
                fh.write(text_out)
            if moved:
                os.remove(path)
    return out


def flag_gene_status(apply=False):
    """
    Apply gene_status_contradictions to CTML already written (mapped and
    review layers; never ctml/reviewed or out-of-scope trials). Returns
    [(trial_id, layer, {gene: fragment}, action)]. With apply=True the
    top-level key is added (text append, so curator comments survive) and a
    mapped trial moves to the review queue.
    """
    import utils.oncology_scope as scope

    ref = text_rules._shared_reference()
    out_of_scope = set(scope.load_report()) | {
        t for t, (d, _) in scope.load_overrides().items() if d == "skip"
    }
    found = []
    for d, layer in ((common.MAPPED_DIR, "mapped"), (common.REVIEW_DIR, "needs_review")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".yaml"):
                continue
            t = f[:-5]
            if t in out_of_scope or os.path.exists(os.path.join(common.REVIEWED_DIR, f)):
                continue
            if layer == "mapped" and os.path.exists(os.path.join(common.REVIEW_DIR, f)):
                continue  # the review copy is what the index publishes
            path = os.path.join(d, f)
            raw = open(path).read()
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict) or ctml.get("gene_status_contradiction"):
                continue
            try:
                inc, _, _ = evidence.eligibility_text(t)
            except (OSError, ValueError, KeyError):
                continue
            hit = text_rules.gene_status_contradictions(ctml, inc, ref)
            if not hit:
                continue
            found.append((t, layer, hit, "moved to review" if layer == "mapped" else "flagged"))
            if apply:
                text = (
                    raw.rstrip("\n")
                    + "\n"
                    + yaml.safe_dump(
                        {"gene_status_contradiction": "; ".join(sorted(hit))},
                        allow_unicode=True,
                        width=1000,
                    )
                )
                with open(os.path.join(common.REVIEW_DIR, f), "w") as fh:
                    fh.write(text)
                if layer == "mapped":
                    os.remove(path)
    return found


def flag_unsupported_genes(apply=False):
    """
    Re-run the mapper's unsupported-gene check (match_criteria_mapper.
    _flag_unsupported_genes, same scan and support rules) on CTML already
    written, against the trial's whole inclusion+exclusion text. Added
    2026-09-27 after 15 short aliases were blocked: criteria the text
    supported only through such a word ("ICF" -> DNMT3B) had passed. An
    expression-only gene (src/trial_config.expression_only_genes) in a
    genomic block is flagged too.

    Mapped and review layers only; ctml/reviewed is never touched, nor are
    out-of-scope trials. Returns [(trial_id, layer, [genes], action)].
    With apply=True the flag is written beside the gene as the mapper writes
    it, and a mapped trial moves to the review queue. A file with curator
    comments is never rewritten (yaml would drop them); it is reported as
    "edited: check by hand".
    """
    import copy

    import src.match_criteria_mapper as mcm
    import src.trial_criteria_to_genes as tcg
    import utils.oncology_scope as scope
    from src import trial_config

    expression_only = set(getattr(trial_config, "expression_only_genes", []))
    syn = rv.gene_synonym_mapping()
    out_of_scope = set(scope.load_report()) | {
        t for t, (dec, _) in scope.load_overrides().items() if dec == "skip"
    }
    found = []
    for d, layer in ((common.MAPPED_DIR, "mapped"), (common.REVIEW_DIR, "needs_review")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".yaml"):
                continue
            t = f[:-5]
            if t in out_of_scope or os.path.exists(os.path.join(common.REVIEWED_DIR, f)):
                continue
            path = os.path.join(d, f)
            raw = open(path).read()
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict):
                continue
            try:
                inc, exc, data = evidence.eligibility_text(t)
            except (OSError, ValueError, KeyError):
                continue
            # The mapper's arm text includes arm descriptions and the title
            # (NCT06265545 names IDH1/FLT3 only in its arms); registry markdown
            # escapes brackets ("\\[MLL\\]", NCT02727803).
            text = (
                "\n".join([inc, exc] + evidence._arm_and_title_text(t, data))
                .replace("\\[", "[")
                .replace("\\]", "]")
            )
            scanned = tcg.TrialCriteriaToGenes(
                trial_criteria=text, synonym_to_symbol=syn
            ).extract_official_gene_symbols()
            new = []
            nodes = [
                g
                for g in text_rules._genomic_nodes(ctml.get("treatment_list"))
                if not g.get("gene_unsupported")
            ]
            for g in nodes:
                probe = [{"genomic": copy.deepcopy(g)}]
                mcm._flag_unsupported_genes(probe, scanned, text, t)
                missing = probe[0]["genomic"].get("gene_unsupported")
                expr = [
                    x
                    for x in (g.get("hugo_symbol"), g.get("fusion_partner"))
                    if x in expression_only
                ]
                if expr:
                    missing = ", ".join(
                        filter(None, [missing] + [f"{x} (expression-only)" for x in expr])
                    )
                if missing:
                    new.append((g, missing))
            if not new:
                continue
            edited = bool(re.search(r"^\s*#", raw, re.M))
            action = (
                "edited: check by hand"
                if edited
                else ("moved to review" if layer == "mapped" else "flagged")
            )
            found.append((t, layer, [m for _, m in new], action))
            if apply and not edited:
                target = os.path.join(common.REVIEW_DIR, f)
                if layer == "mapped" and os.path.exists(target):
                    continue
                for g, missing in new:
                    g["gene_unsupported"] = missing
                os.makedirs(common.REVIEW_DIR, exist_ok=True)
                with open(target, "w") as fh:
                    fh.write(yaml.dump(ctml, sort_keys=False))
                if layer == "mapped":
                    os.remove(path)
    return found


# -------------------------------------------------------------------- build


# -------------------------------------------------------------------- html


# ------------------------------------------------------------ accept/check


# --------------------------------------------------------------------- CLI


def main(argv=None):
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
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
    ex = sub.add_parser("exclude")
    ex.add_argument("trial")
    ex.add_argument("--reviewer", required=True)
    ex.add_argument("--reason", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "queue":
        ref = text_rules.Reference()
        for tid in gate._queue_ids():
            an = evidence.analyse(tid, ref)
            print(f"{tid}\t{','.join(an['flags'])}\t{an['title'][:80]}")
    elif args.cmd == "sheets":
        rows = sheets.write_sheets(
            args.trials or gate._queue_ids(),
            "Review queue" if not args.trials else "Selected trials",
        )
        print(f"{len(rows)} sheets in {common.SHEET_DIR}/ - open {common.SHEET_DIR}/index.html")
    elif args.cmd == "audit":
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
    elif args.cmd == "check":
        path, layer = common._layer_of(args.trial)
        raw = open(path).read()
        found = gate.problems(yaml.safe_load(raw), raw)
        print(
            f"{args.trial} ({layer}): "
            + ("ready to accept" if not found else "\n  - " + "\n  - ".join(found))
        )
    elif args.cmd == "accept":
        print(
            f"accepted -> {gate.accept(args.trial, args.reviewer, args.note, args.replace)}; logged in {common.LOG_FILE}"
        )
    elif args.cmd == "flag-exclusions":
        found = flag_exclusions(apply=args.apply)
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
    elif args.cmd == "clear-stale-gene-flags":
        found = clear_stale_gene_flags(apply=args.apply)
        for t, genes, moved in found:
            print(f"{t}\t{','.join(genes)}\t{'-> mapped' if moved else 'stays in review'}")
        print(
            f"{len(found)} trials, {sum(len(g) for _, g, _ in found)} flags"
            + (" cleared" if args.apply else " would be cleared; --apply to write")
        )
    elif args.cmd == "fix-all-lineage":
        found = fix_all_lineage(apply=args.apply)
        for t, layer, n in found:
            print(f"{t}\t{layer}\t{n} B-ALL node(s) given a T-ALL alternative")
        print(
            f"{len(found)} trials"
            + (" updated" if args.apply else " would be updated; --apply to write")
        )
    elif args.cmd == "resolve-remap-drops":
        found = resolve_remap_drops(apply=args.apply)
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
    elif args.cmd == "fix-genomic-notation":
        found = fix_genomic_notation(apply=args.apply)
        for t, layer, n, rearr in found:
            print(f"{t}\t{layer}\tH3C3 x{n}\trearranged: {','.join(rearr) or '-'}")
        print(
            f"{len(found)} trials"
            + (" updated" if args.apply else " would be updated; --apply to write")
        )
    elif args.cmd == "flag-gene-status":
        found = flag_gene_status(apply=args.apply)
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
    elif args.cmd == "flag-unsupported-genes":
        found = flag_unsupported_genes(apply=args.apply)
        for t, layer, genes, action in found:
            print(f"{t}\t{layer}\t{action}\t{'; '.join(genes)}")
        moved = sum(1 for _, layer, _, a in found if a == "moved to review")
        print(
            f"{len(found)} trials ({moved} mapped would move to review)"
            if not args.apply
            else f"{len(found)} trials flagged; {moved} mapped ones moved to the review queue"
        )
    elif args.cmd == "exclude":
        layers = gate.exclude(args.trial, args.reviewer, args.reason)
        print(
            f"{args.trial} excluded (ref/scope_overrides.tsv; logged in {common.LOG_FILE}); "
            f"its copies in {', '.join(layers) or 'no layer'} are left in place and dropped at the next index build"
        )


if __name__ == "__main__":
    main()
