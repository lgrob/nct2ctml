"""
Build a flat, queryable index of curated trials from the CTML files.

Why this exists
---------------
CTML is a nested boolean tree. "Does this tree evaluate true for sample X"
cannot be expressed as a query over nested JSON, so every consumer would have
to implement a tree evaluator - the work MatchMiner's matchengine used to do.
This flattens the expensive, semantics-heavy dimension (diagnosis) once, at
build time, where it can be tested, leaving a downstream pipeline an equi-join
on a string.

The index is SCREENING, not decisive
------------------------------------
Rows are a union of everything a trial could match, so the index narrows the
corpus to a handful of candidates; the CTML file is then consulted for the
actual eligibility call. Exclusions and mixed and/or nesting do not denormalise
losslessly, and pretending otherwise is how a flat index starts quietly
disagreeing with the source. `include` is carried so a consumer can drop the
obvious non-starters, but a row is never by itself a match.

Consequences worth knowing:
- Diagnosis subtrees are expanded, so `Rhabdomyosarcoma` emits its six codes.
  A consumer never needs the Oncotree hierarchy.
- `_SOLID_` and `_LIQUID_` are expanded too, so a consumer never needs to know
  MatchMiner's wildcards exist.
- Both the Oncotree code and the display name are emitted. Codes are stable
  across Oncotree releases and display names are not - `H3 K27M-Mutant` became
  `H3 K27-Altered` - so join on the code where you can.
- `source_term` keeps the term the trial actually stated, so a match can be
  explained back to the curated file rather than to an expanded code.
- A fusion criterion carries `fusion_partner` when the trial names both genes,
  and `fusion` is the HGNC fusion notation ("EWSR1::FLI1", first-named gene
  first). The row is emitted from both genes' sides - hugo_symbol EWSR1 with
  partner FLI1, and hugo_symbol FLI1 with partner EWSR1 when FLI1 is a panel
  gene - so a join works whichever gene the fusion caller reports first.
  Match the pair unordered: trial text does not reliably give 5'/3' order.
  An empty partner means any fusion of the gene. `fusion_partner_check`
  says why a stated partner was not kept (utils/reference_validation.
  fusion_partner), in which case the row means any fusion of the gene.
- `gene_check` is "unsupported: <genes>" when the mapper kept a gene the
  model returned but the text scan did not find (gene_unsupported); such a
  trial was written to ctml/needs-review.
- `protein_change` is HGVS three-letter notation on the gene's MANE Select
  protein ("p.Val600Glu"), the notation VEP writes in CSQ_HGVSp after the
  accession. It is filled only when `protein_check` is `verified`, meaning
  every residue it names was found at that position in
  ref/mane_select_proteins.tsv (utils/protein_change.py). Histone H3 changes
  are renumbered from the literature's mature-protein count, so "K27M" is
  `p.Lys28Met`. What the trial wrote stays in `protein_change_stated`. A
  row whose change fails the check keeps an empty `protein_change` and the
  reason in `protein_check`, so a join on it cannot silently hit the wrong
  residue; `--strict` makes such a row fail the build.

Outputs are deterministic: the same inputs produce byte-identical files, and
`manifest.json` records the row counts, the Oncotree file's checksum and each
output's checksum. That is what lets you say which trial set produced a given
report, which a mutable database cannot without separate audit machinery.

Usage:
    python -m utils.build_trial_index [--out index] [--strict]
        # every mapped trial, with review_status: cache/ctml (mapped), then
        # ctml/needs-review, then ctml/reviewed, a later copy replacing an
        # earlier one
    python -m utils.build_trial_index --source ctml/reviewed
        # one directory only; review_status is `reviewed` only for that one

Input and review status
-----------------------
By default the index covers every trial the pipeline has mapped, not just the
reviewed ones, so a patient can be screened against the whole corpus from
the first full run. `trials.tsv` says what each trial's criteria are worth:
`review_status` is `reviewed` (a curator signed it off), `needs_review` (the
mapper flagged it: no diagnosis, or a protein change that failed its check)
or `mapped` (machine output nobody has read), with `reviewed` as 0/1 and
`source_file` naming the file the rows came from. A hit on an unreviewed
trial is a lead for a curator, not a finding; route it accordingly.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import yaml
from loguru import logger

import config
from utils import protein_change
from utils.oncotree import get_all_oncotree_data, get_lineage
from utils.reference_validation import _oncotree, canonical_gene, fusion_partner

# MatchMiner's wildcards are not Oncotree nodes, so they are defined here
# rather than looked up. Everything haematological is liquid and everything
# else is solid, including the "Other" root - a basket solid-tumour trial
# would accept a cancer of unknown primary, and excluding it would silently
# narrow the population. Kept as one constant because it is a clinical
# convention, not a fact about the tree.
LIQUID_ROOTS = frozenset({"Lymphoid", "Myeloid"})

_AGE_BOUND = re.compile(r"^\s*(>=|<=|>|<)\s*([0-9]*\.?[0-9]+)\s*$")

DIAGNOSIS_COLUMNS = ["trial_id", "arm_code", "oncotree_code", "oncotree_name",
                    "source_term", "from_basket", "include"]
GENOMIC_COLUMNS = ["trial_id", "arm_code", "hugo_symbol", "variant_category",
                   "cnv_call", "protein_change", "protein_change_stated",
                   "protein_change_kind", "protein_refseq", "protein_ensembl",
                   "protein_check", "fusion_partner", "fusion", "fusion_partner_check",
                   "gene_check", "variant_classification", "include"]
TRIAL_COLUMNS = ["trial_id", "source", "nct_id", "protocol_no", "short_title",
                 "phase", "status", "review_status", "reviewed", "source_file", "layer_conflict",
                 "age_label", "age_min", "age_min_inclusive",
                 "age_max", "age_max_inclusive", "n_diagnosis_codes", "n_genes"]

# Input layers, lowest precedence first. The status says what a row is worth:
# `reviewed` was signed off by a curator, `needs_review` is machine output the
# mapper itself flagged (no diagnosis, or a protein change that failed its
# reference check), `mapped` is machine output nobody has looked at yet.
DEFAULT_LAYERS = [(config.CTML_MAPPED_PATH, "mapped"),
                  (config.CTML_REVIEW_PATH, "needs_review"),
                  (config.CTML_REVIEWED_PATH, "reviewed")]


def _name_to_code():
    """Oncotree display name -> code. Both are emitted so consumers can pick."""
    _, codes, _ = _oncotree()
    mapping = {}
    for code, name in codes.items():
        mapping.setdefault(name, code)
    return mapping


def _basket_members():
    """(solid, liquid) display-name sets, from the level_1 roots."""
    level_1, level_1_to_all = get_all_oncotree_data()
    liquid, solid = set(), set()
    for root in level_1:
        (liquid if root in LIQUID_ROOTS else solid).update(level_1_to_all[root] | {root})
    return solid, liquid


@lru_cache(maxsize=1)
def _population_reference():
    """(descendants, codable, solid, liquid), read once per process."""
    parent, _, descendants = get_lineage()
    has_nos_child = {parent[name] for name in parent if name.endswith(", NOS")}
    codable = frozenset(name for name in descendants if name not in has_nos_child)
    solid, liquid = _basket_members()
    return descendants, codable, frozenset(solid), frozenset(liquid)


def diagnosis_population(terms):
    """
    The Oncotree nodes a patient can be coded to that a set of trial
    diagnoses reaches.

    Patients are coded at the most specific node the pathology supports. That
    is usually a leaf, but not always: only 20 of Oncotree's 170 internal
    nodes have a ", NOS" child, so an osteosarcoma that is not subtyped further
    is coded `Osteosarcoma` itself. The one node a patient is never coded to is
    a parent that has a ", NOS" child - that patient goes to the NOS leaf
    instead. So the codable nodes are every node except those 20 parents, and
    the patients a trial reaches are the codable nodes under its diagnoses.
    Two diagnosis sets that reach the same codable nodes select the same
    patients, whatever they are called.

    This is narrower than the index's expansion, which emits every descendant
    so that a join works however a consumer codes its patients. The two agree
    whenever patients are coded as above. If that stops being true, this is
    the function to change.

    `_SOLID_` and `_LIQUID_` expand as they do in the index. A term that is not
    an Oncotree node reaches nothing codable; it is kept as itself, so it still
    agrees with an identical string and disagrees with everything else.
    """
    descendants, codable, solid, liquid = _population_reference()
    reached = set()
    for term in terms:
        if term == "_SOLID_":
            members = solid
        elif term == "_LIQUID_":
            members = liquid
        else:
            members = descendants.get(term, {term})
        reached |= (members & codable) or {term}
    return reached


def _walk(node, on_leaf, arm_code=""):
    """Visit every clinical/genomic leaf, carrying the arm it was found under."""
    if isinstance(node, dict):
        for key in ("clinical", "genomic"):
            if isinstance(node.get(key), dict):
                on_leaf(key, node[key], arm_code)
        for value in node.values():
            _walk(value, on_leaf, arm_code)
    elif isinstance(node, list):
        for value in node:
            _walk(value, on_leaf, arm_code)


def _parse_age_bounds(values):
    """
    The trial's numeric age window, as (min, min_inclusive, max, max_inclusive).

    Sibling clinical nodes under `and` are intersected by the match engine, so
    several bounds on one trial are combined to the most restrictive. The
    trial-level `age` string is a label - "Children" - and matches no patient
    field, so it is carried for display only and never used here.
    """
    low, low_incl, high, high_incl = None, None, None, None
    for value in values:
        match = _AGE_BOUND.match(str(value))
        if not match:
            continue
        operator, number = match.group(1), float(match.group(2))
        if operator in (">=", ">"):
            if low is None or number > low:
                low, low_incl = number, operator == ">="
        else:
            if high is None or number < high:
                high, high_incl = number, operator == "<="
    return low, low_incl, high, high_incl


def _read_trials(source_dir):
    """Every CTML file in `source_dir`, as (trial_id, dict, path), name-sorted."""
    trials = []
    if not os.path.isdir(source_dir):
        logger.warning(f"{source_dir} does not exist; contributing no trials")
        return trials
    for filename in sorted(os.listdir(source_dir)):
        stem, extension = os.path.splitext(filename)
        if extension not in (".json", ".yaml", ".yml"):
            continue
        path = os.path.join(source_dir, filename)
        with open(path) as handle:
            trials.append((stem, json.load(handle) if extension == ".json"
                           else yaml.safe_load(handle), path))
    return trials


def _layers(source):
    """
    [(directory, review_status)] from a directory, a list of layers, or None.

    A single directory is one layer. It counts as `reviewed` only when it is
    the reviewed directory itself; anything else is `mapped`, because a
    status that cannot be established must not be reported as review.
    """
    if source is None:
        return list(DEFAULT_LAYERS)
    if isinstance(source, str):
        reviewed = os.path.realpath(source) == os.path.realpath(config.CTML_REVIEWED_PATH)
        return [(source, "reviewed" if reviewed else "mapped")]
    return list(source)


CONFLICT_COLUMNS = ["trial_id", "published_file", "published_status", "published_mtime",
                    "newer_file", "newer_status", "newer_mtime", "conflict"]


def _mtime(path):
    return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collect(layers):
    """
    ({trial_id: (trial, path, status)}, [conflict rows]). Later layers
    replace earlier ones.

    A trial routed to ctml/needs-review by one run and mapped cleanly by a
    later one has two copies. The needs-review copy still wins, because it
    may hold a curator's edits in progress (decision D6, 2026-09-24: keep it
    and report the conflict, rather than delete it or let the newer file
    win). The conflict is reported here, not resolved: the trial row gets
    layer_conflict = newer_mapped_copy, and the pair is listed in
    layer_conflicts.tsv for a curator to settle.

    "Newer" means a later file modification time. The CTML itself carries
    no mapping time, and both directories are written only by the mapper
    and by curators, so the mtime is the only record there is. A copy or
    sync that resets mtimes can hide a conflict or invent one.

    An older mapped copy under a needs-review copy is the normal case (the
    last run flagged the trial) and is not reported. Nor is a reviewed copy
    over newer machine output: curation is expected to lag remapping.
    """
    chosen, seen = {}, {}
    for directory, status in layers:
        for trial_id, trial, path in _read_trials(directory):
            if trial_id in chosen:
                logger.debug(f"{trial_id} | {status} copy in {directory} replaces "
                             f"the {chosen[trial_id][2]} copy")
            chosen[trial_id] = (trial, path, status)
            seen.setdefault(trial_id, {})[status] = path
    conflicts = []
    for trial_id, (_, path, status) in sorted(chosen.items()):
        mapped = seen[trial_id].get("mapped")
        if status == "needs_review" and mapped and os.path.getmtime(mapped) > os.path.getmtime(path):
            conflicts.append({"trial_id": trial_id, "published_file": path, "published_status": status,
                              "published_mtime": _mtime(path), "newer_file": mapped,
                              "newer_status": "mapped", "newer_mtime": _mtime(mapped),
                              "conflict": "newer_mapped_copy"})
            logger.warning(f"{trial_id} | a newer clean mapping ({mapped}) exists under the "
                           f"needs-review copy ({path}); the needs-review copy is published, "
                           f"and the conflict is listed in layer_conflicts.tsv")
    return dict(sorted(chosen.items())), conflicts


def _fusion_fields(leaf):
    """fusion_partner, fusion ("A::B") and fusion_partner_check for one leaf."""
    partner = leaf.get("fusion_partner") or ""
    unverified = leaf.get("fusion_partner_unverified") or ""
    gene = leaf.get("hugo_symbol") or ""
    if partner:
        # Re-checked here too: curated YAML never passed through the mapper.
        resolved, status = fusion_partner(partner)
        if resolved and resolved != gene:
            return {"fusion_partner": resolved, "fusion": f"{gene}::{resolved}",
                    "fusion_partner_check": status}
        unverified = partner
    if unverified:
        return {"fusion_partner": "", "fusion": "",
                "fusion_partner_check": f"unverified: {unverified}"}
    return {"fusion_partner": "", "fusion": "", "fusion_partner_check": ""}


def index_trial(trial_id, trial, descendants, solid, liquid, name_to_code):
    """(trial_row, diagnosis_rows, genomic_rows) for one curated trial."""
    diagnoses, genomics, ages = [], [], []

    def on_leaf(kind, leaf, arm_code):
        if kind == "clinical":
            if leaf.get("age_numerical"):
                ages.append(leaf["age_numerical"])
            term = leaf.get("oncotree_primary_diagnosis")
            if term:
                diagnoses.append((arm_code, term))
        else:
            category = str(leaf.get("variant_category") or "")
            genomics.append({
                "arm_code": arm_code,
                "hugo_symbol": leaf.get("hugo_symbol") or "",
                "variant_category": category.lstrip("!"),
                "cnv_call": leaf.get("cnv_call") or "",
                # An unverified change is carried so the index reports it
                # (protein_check) instead of silently publishing a gene-level row.
                "protein_change": leaf.get("protein_change")
                                  or leaf.get("wildcard_protein_change")
                                  or leaf.get("protein_change_unverified") or "",
                "variant_classification": leaf.get("variant_classification") or "",
                "include": 0 if category.startswith("!") else 1,
                **_fusion_fields(leaf),
                # A gene the mapper could not find in the criteria text; the
                # row stands but a curator has to confirm it.
                "gene_check": (f"unsupported: {leaf['gene_unsupported']}"
                               if leaf.get("gene_unsupported") else ""),
            })
            partner = genomics[-1]["fusion_partner"]
            # The same fusion seen from the partner's side, when the panel
            # reports the partner: joins then work whichever gene comes first.
            if partner and canonical_gene(partner) == partner:
                genomics.append(dict(genomics[-1], hugo_symbol=partner,
                                     fusion_partner=genomics[-1]["hugo_symbol"]))

    for step in (trial.get("treatment_list") or {}).get("step") or []:
        _walk(step.get("match"), on_leaf)
        for arm in step.get("arm") or []:
            # Arms may carry their own match tree; none of the curated trials
            # does today, but the schema allows it and ignoring it would drop
            # criteria silently.
            if arm.get("match"):
                _walk(arm["match"], on_leaf, arm.get("arm_code") or "")
    _walk(trial.get("match"), on_leaf)

    diagnosis_rows, seen = [], set()
    for arm_code, term in diagnoses:
        if term == "_SOLID_":
            members, basket = solid, 1
        elif term == "_LIQUID_":
            members, basket = liquid, 1
        else:
            members, basket = descendants.get(term, {term}), 0
        for name in sorted(members):
            key = (arm_code, name)
            if key in seen:
                continue
            seen.add(key)
            diagnosis_rows.append({
                "trial_id": trial_id, "arm_code": arm_code,
                "oncotree_code": name_to_code.get(name, ""), "oncotree_name": name,
                "source_term": term, "from_basket": basket, "include": 1,
            })

    genomic_rows, seen_genomic = [], set()
    for row in genomics:
        key = tuple(sorted(row.items()))
        if key in seen_genomic:
            continue
        seen_genomic.add(key)
        genomic_rows.append({"trial_id": trial_id, **row})

    low, low_incl, high, high_incl = _parse_age_bounds(ages)
    trial_row = {
        "trial_id": trial_id,
        "source": "CTIS" if not str(trial.get("nct_id") or "").startswith("NCT") else "CTGOV",
        "nct_id": trial.get("nct_id") or "",
        "protocol_no": trial.get("protocol_no") or "",
        "short_title": (trial.get("short_title") or "").replace("\t", " ").replace("\n", " "),
        "phase": trial.get("phase") or "",
        "status": trial.get("status") or "",
        "age_label": trial.get("age") or "",
        "age_min": "" if low is None else low,
        "age_min_inclusive": "" if low_incl is None else int(low_incl),
        "age_max": "" if high is None else high,
        "age_max_inclusive": "" if high_incl is None else int(high_incl),
        "n_diagnosis_codes": len(diagnosis_rows),
        "n_genes": len({r["hugo_symbol"] for r in genomic_rows if r["hugo_symbol"]}),
    }
    return trial_row, diagnosis_rows, genomic_rows


def _normalise_protein_changes(genomic_rows):
    """Rewrite each row's protein change as checked HGVS, in place."""
    counts = Counter()
    for row in genomic_rows:
        stated = row["protein_change"]
        row.update(protein_change="", protein_change_stated=stated, protein_change_kind="",
                   protein_refseq="", protein_ensembl="", protein_check="")
        if not stated:
            continue
        result = protein_change.normalise(row["hugo_symbol"], stated)
        row.update(protein_change=result.hgvs, protein_change_kind=result.kind,
                   protein_refseq=result.refseq_protein,
                   protein_ensembl=result.ensembl_protein, protein_check=result.status)
        counts[result.status] += 1
        if not result.verified:
            logger.warning(f"{row['trial_id']} | {row['hugo_symbol']} {stated!r} not emitted "
                           f"as HGVS: {result.status} ({result.detail})")
    return dict(sorted(counts.items()))


def build(source=None, out_dir="index", strict=False):
    """
    Build the index. `source` is None (the default layers), one directory,
    or a list of (directory, review_status) layers, lowest precedence first.
    """
    layers = _layers(source)
    _, _, descendants = get_lineage()
    solid, liquid = _basket_members()
    name_to_code = _name_to_code()

    trial_rows, diagnosis_rows, genomic_rows = [], [], []
    chosen, conflicts = _collect(layers)
    conflict_of = {c["trial_id"]: c["conflict"] for c in conflicts}
    for trial_id, (trial, path, status) in chosen.items():
        trial_row, diagnoses, genomics = index_trial(
            trial_id, trial, descendants, solid, liquid, name_to_code)
        trial_row.update(review_status=status, reviewed=int(status == "reviewed"),
                         source_file=path, layer_conflict=conflict_of.get(trial_id, ""))
        if not diagnoses:
            # Mirrors trial_map_manager._destination_for: a trial with no
            # diagnosis would match every sample, so it is indexed but flagged
            # rather than dropped - dropping makes it invisible.
            logger.warning(f"{trial_id} | no diagnosis criterion; indexed with zero "
                           f"diagnosis rows, so it can never be screened in.")
        trial_rows.append(trial_row)
        diagnosis_rows.extend(diagnoses)
        genomic_rows.extend(genomics)

    protein_checks = _normalise_protein_changes(genomic_rows)
    failed = {k: v for k, v in protein_checks.items() if k != protein_change.VERIFIED}
    if strict and failed:
        raise SystemExit(f"--strict: protein changes failed the reference check: {failed}")

    os.makedirs(out_dir, exist_ok=True)
    written = {}
    for name, columns, rows in (("trials.tsv", TRIAL_COLUMNS, trial_rows),
                                ("trial_diagnosis.tsv", DIAGNOSIS_COLUMNS, diagnosis_rows),
                                ("trial_genomic.tsv", GENOMIC_COLUMNS, genomic_rows),
                                ("layer_conflicts.tsv", CONFLICT_COLUMNS, conflicts)):
        path = os.path.join(out_dir, name)
        with open(path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t",
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        written[name] = {"rows": len(rows), "sha256": _sha256(path)}

    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "layers": [{"directory": d, "review_status": s} for d, s in layers],
        "review_status": dict(sorted(Counter(r["review_status"] for r in trial_rows).items())),
        "trials": len(trial_rows),
        "layer_conflicts": len(conflicts),
        "oncotree_file": config.ONCOTREE_TXT_FILE_PATH,
        "oncotree_sha256": _sha256(config.ONCOTREE_TXT_FILE_PATH),
        "liquid_roots": sorted(LIQUID_ROOTS),
        "protein_reference_file": protein_change.REFERENCE,
        "protein_reference_sha256": _sha256(protein_change.REFERENCE),
        "protein_checks": protein_checks,
        "outputs": written,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=None,
                        help="a single directory of CTML files (.json/.yaml); default: "
                             "the mapped, needs-review and reviewed layers from config.py")
    parser.add_argument("--out", default="index", help="output directory")
    parser.add_argument("--strict", action="store_true",
                        help="fail if any protein change does not match its reference protein")
    args = parser.parse_args()

    manifest = build(args.source, args.out, strict=args.strict)
    print(f"Indexed {manifest['trials']} trials: {manifest['review_status']}")
    for name, info in manifest["outputs"].items():
        print(f"  {name:22} {info['rows']:>7,} rows")
    print(f"  manifest.json          oncotree {manifest['oncotree_sha256'][:12]}")
    print(f"  protein changes        {manifest['protein_checks'] or 'none'}")
    print(f"  layer conflicts        {manifest['layer_conflicts']} (see layer_conflicts.tsv)")


if __name__ == "__main__":
    main()
