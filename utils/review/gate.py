"""
The review gate: what accept refuses (problems), accepting a trial into
ctml/reviewed with a line in the review log, excluding one from scope, and
which trials make up the queue and the audit sample.
"""

import csv
import datetime
import hashlib
import os
import random
import re

import yaml

import src.text_rules as text_rules
import utils.protein_change as protein_change
import utils.reference_validation as rv
import utils.review.common as common
from utils.oncotree import get_lineage


def problems(ctml, raw):
    """Reasons `accept` refuses this file; empty when it may be accepted."""
    from src.trial_map_manager import TrialMapManager

    out = []
    for k in common.FLAG_KEYS:
        if re.search(rf"^\s*{k}\s*:", raw, re.M):
            out.append(f"still flagged: {k}")
    import src.match_criteria_mapper as mcm

    for gene in mcm.find_unsatisfiable_genes(ctml.get("treatment_list", ctml)):
        out.append(f"requires and forbids {gene} under one AND: matches nobody")
    if not TrialMapManager._has_diagnosis(ctml):
        out.append("no diagnosis")
    ref_names = set(get_lineage()[2]) | common.WILDCARDS
    got = text_rules.collect(ctml)
    for d in got["diagnoses"]:
        # "!Name" excludes that diagnosis and its subtypes (quote it in YAML:
        # a bare leading ! is a YAML tag).
        if str(d).lstrip("!") not in ref_names:
            out.append(f"not an OncoTree name: {d!r}")
    if got["diagnoses"] and all(str(d).startswith("!") for d in got["diagnoses"]):
        out.append("only excluded diagnoses: add the diagnosis the trial enrols")
    for g in got["genomic"]:
        sym = str(g.get("hugo_symbol", ""))
        if not rv.canonical_gene(sym):
            out.append(f"not an accepted gene symbol: {sym!r}")
        if g.get("fusion_partner") and rv.fusion_partner(str(g["fusion_partner"]))[0] != str(
            g["fusion_partner"]
        ):
            out.append(f"fusion partner not a gene symbol: {g['fusion_partner']!r}")
        if g.get("protein_change"):
            r = protein_change.normalise(sym, str(g["protein_change"]))
            if r.status != protein_change.VERIFIED:
                out.append(f"{sym} {g['protein_change']}: {r.status} ({r.detail})")
    return out


def accept(trial_id, reviewer, note="", replace=False, today=None):
    path, layer = common._layer_of(trial_id)
    if layer == "reviewed":
        raise SystemExit(f"{trial_id} is already in {common.REVIEWED_DIR}")
    if not reviewer.strip():
        raise SystemExit("--reviewer is required")
    raw = open(path).read()
    ctml = yaml.safe_load(raw)
    found = problems(ctml, raw)
    if found:
        raise SystemExit(f"{trial_id} not accepted:\n  - " + "\n  - ".join(found))
    target = os.path.join(common.REVIEWED_DIR, f"{trial_id}.yaml")
    if os.path.exists(target) and not replace:
        raise SystemExit(
            f"{target} exists; pass --replace to supersede it (the old copy is kept as .prev)"
        )
    today = today or datetime.date.today().isoformat()
    # Stamp curated_on in place so the curator's formatting survives.
    if re.search(r"^curated_on:.*$", raw, re.M):
        raw = re.sub(r"^curated_on:.*$", f"curated_on: '{today}'", raw, count=1, flags=re.M)
    else:
        raw = f"curated_on: '{today}'\n" + raw
    resolved = _flags_at_entry(trial_id)
    if os.path.exists(target):
        os.replace(target, target + ".prev")
    os.makedirs(common.REVIEWED_DIR, exist_ok=True)
    with open(target, "w") as fh:
        fh.write(raw)
    if layer == "needs_review":
        os.remove(path)
    new_log = not os.path.exists(common.LOG_FILE)
    with open(common.LOG_FILE, "a", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        if new_log:
            w.writerow(common.LOG_COLUMNS)
        w.writerow(
            [
                today,
                trial_id,
                reviewer,
                layer,
                ",".join(resolved),
                hashlib.sha256(raw.encode()).hexdigest(),
                note.replace("\t", " ").replace("\n", " "),
            ]
        )
    return target


def exclude(trial_id, reviewer, reason, today=None):
    """
    Take a trial out of scope: a "skip" row in ref/scope_overrides.tsv, which
    map --all and the index build both honour, and a line in the review log.
    The trial's YAML files are left in place; the index ignores them.
    """
    import utils.oncology_scope as scope

    OVERRIDES = scope.OVERRIDES
    if not reviewer.strip() or not reason.strip():
        raise SystemExit("--reviewer and --reason are required")
    if re.search(r"[\t\n]", reason):
        raise SystemExit("--reason must be one line without tabs")
    current = scope.load_overrides(OVERRIDES).get(trial_id)
    if current and current[0] == "skip":
        raise SystemExit(f"{trial_id} is already excluded: {current[1]}")
    if current:
        raise SystemExit(
            f"{trial_id} has a 'map' override ({current[1]}); edit {OVERRIDES} by hand"
        )
    layers = [
        layer
        for d, layer in (
            (common.REVIEW_DIR, "needs_review"),
            (common.MAPPED_DIR, "mapped"),
            (common.REVIEWED_DIR, "reviewed"),
        )
        if os.path.exists(os.path.join(d, f"{trial_id}.yaml"))
    ]
    today = today or datetime.date.today().isoformat()
    text = open(OVERRIDES).read() if os.path.exists(OVERRIDES) else "trial_id\tdecision\treason\n"
    with open(OVERRIDES, "w") as fh:
        fh.write(
            text
            + ("" if text.endswith("\n") else "\n")
            + f"{trial_id}\tskip\t{reason} ({reviewer}, {today})\n"
        )
    new_log = not os.path.exists(common.LOG_FILE)
    with open(common.LOG_FILE, "a", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        if new_log:
            w.writerow(common.LOG_COLUMNS)
        w.writerow([today, trial_id, reviewer, ",".join(layers) or "none", "excluded", "", reason])
    return layers


def _flags_at_entry(trial_id):
    """
    The flags the mapper originally set (for the log). The curator's copy has
    them deleted by the time accept runs, so read the mapper's own output:
    the review copy's .prev backup(s), then the mapped copy, then the file
    as it stands. Also the reason for no diagnosis.
    """
    backups = (
        sorted(
            (f for f in os.listdir(common.REVIEW_DIR) if f.startswith(f"{trial_id}.yaml.prev")),
            key=lambda f: (len(f), f),
        )
        if os.path.isdir(common.REVIEW_DIR)
        else []
    )
    for p in ([os.path.join(common.REVIEW_DIR, backups[0])] if backups else []) + [
        os.path.join(common.MAPPED_DIR, f"{trial_id}.yaml"),
        os.path.join(common.REVIEW_DIR, f"{trial_id}.yaml"),
    ]:
        if os.path.exists(p):
            raw = open(p).read()
            return [k for k in common.FLAG_KEYS if re.search(rf"^\s*{k}\s*:", raw, re.M)]
    return []


def _not_in_index():
    """Trials the index leaves out: out of scope per the report, or a skip override."""
    import utils.oncology_scope as scope

    return set(scope.load_report()) | {
        t for t, (dec, _) in scope.load_overrides().items() if dec == "skip"
    }


def _queue_ids():
    """The review queue as the index sees it: no out-of-scope trials, none already reviewed."""
    gone = _not_in_index()
    reviewed = (
        {f[:-5] for f in os.listdir(common.REVIEWED_DIR)}
        if os.path.isdir(common.REVIEWED_DIR)
        else set()
    )
    return sorted(
        f[:-5]
        for f in os.listdir(common.REVIEW_DIR)
        if f.endswith(".yaml") and f[:-5] not in gone and f[:-5] not in reviewed
    )


def audit_sample(n, seed):
    """n random mapped trials that are neither reviewed nor in the queue (roadmap 3.4)."""
    skip = {
        f[:-5]
        for d in (common.REVIEWED_DIR, common.REVIEW_DIR)
        if os.path.isdir(d)
        for f in os.listdir(d)
    } | _not_in_index()
    pool = sorted(
        f[:-5] for f in os.listdir(common.MAPPED_DIR) if f.endswith(".yaml") and f[:-5] not in skip
    )
    return sorted(random.Random(seed).sample(pool, min(n, len(pool)))), len(pool)
