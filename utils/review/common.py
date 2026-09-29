"""
What every part of the review helper shares: where the layers are, the flag
keys the mapper writes, the advice shown for each, and how a flag value is
read.

The path constants are module globals on purpose: tests redirect them
(tests/support.temporary_layers), so read them as common.MAPPED_DIR, never
through `from ... import MAPPED_DIR`.
"""

import os
from dataclasses import dataclass, field

MAPPED_DIR = "cache/ctml"


REVIEW_DIR = "ctml/needs-review"


REVIEWED_DIR = "ctml/reviewed"


LOG_FILE = "ctml/review_log.tsv"


SHEET_DIR = "review_sheets"


LOG_COLUMNS = ["date", "trial_id", "reviewer", "from_layer", "flags_resolved", "sha256", "note"]


# Keys the mapper writes to mark an item for review. `accept` refuses a file
# that still holds any of them: deleting the key is how a curator confirms
# the item, deleting the item is how they reject it.
FLAG_KEYS = (
    "gene_unsupported",
    "diagnosis_off_list",
    "diagnosis_excluded",
    "genomic_contradiction",
    "remap_dropped_diagnoses",
    "gene_status_contradiction",
    "protein_change_unverified",
    "protein_change_check",
    "fusion_partner_unverified",
)


WILDCARDS = {"_SOLID_", "_LIQUID_"}


ADVICE = {
    "no_diagnosis": "No diagnosis: as it stands the trial matches every patient. Add "
    "oncotree_primary_diagnosis entries, or _SOLID_ / _LIQUID_ for a basket trial.",
    "gene_unsupported": "The model returned a gene the text scan did not find. If the text requires it, "
    "delete the `gene_unsupported:` line; if not, delete the whole genomic criterion.",
    "diagnosis_off_list": "A diagnosis was answered outside the candidate list the model was offered. "
    "Keep or remove that diagnosis in the match tree, then delete the top-level "
    "`diagnosis_off_list:` line.",
    "diagnosis_excluded": "This diagnosis is named in the exclusion criteria and nowhere in the inclusion "
    "criteria, title or conditions: the trial probably excludes it. Delete it from the "
    "match tree, or, when a broader diagnosis the trial enrols contains it, add it as "
    "`oncotree_primary_diagnosis: '!Name'` (quoted) beside that diagnosis. Then delete "
    "the top-level `diagnosis_excluded:` line.",
    "gene_role_dropped": "Information, not a flag: the model read these genes as something other than an entry "
    "requirement (risk group, one cohort, conditional, an alternative route, an example, "
    "expression or germline) and kept them out of the match tree. They are published in "
    "trials.tsv as genes_not_required. Add a gene back only if every patient must carry it.",
    "gene_status_contradiction": "The match tree requires an alteration in a gene that the inclusion text says "
    "must be absent (wild type, negative, 'no ... mutation') or does not matter "
    "('with or without'). Remove or negate the criterion, then delete the top-level "
    "`gene_status_contradiction:` line.",
    "remap_dropped_diagnoses": "A re-map (2026-09-27) dropped these diagnoses, and the exclusion text does not "
    "explain it, so patients who matched before would no longer match. The previous "
    "version is kept as <trial>.yaml.prev. Add back the ones the trial enrols, then "
    "delete the top-level `remap_dropped_diagnoses:` line.",
    "genomic_contradiction": "The match tree requires and forbids the same gene under one AND, so it matches "
    "nobody. Often an exclusion written for the whole gene ('!Any Variation') where the "
    "text excludes one variant, or a gene also required as a fusion partner. Narrow or "
    "remove the exclusion, then delete the top-level `genomic_contradiction:` line.",
    "protein_change_unverified": "The stated protein change does not match the reference protein. Write the "
    "correct change as `protein_change:` (it is re-checked), or drop it; then "
    "delete `protein_change_unverified:` and `protein_change_check:`.",
    "fusion_partner_unverified": "The fusion partner is not an official gene symbol. Replace the line with "
    "`fusion_partner: <symbol>` or delete it.",
}


@dataclass
class Item:
    kind: str  # diagnosis | gene | age | protein | partner | no_diagnosis
    value: str
    flag: str = ""  # a FLAG_KEYS entry, or "no_diagnosis"
    side: str = ""  # inclusion | exclusion (genomic include flag)
    evidence: list = field(default_factory=list)  # [(section, snippet html)]
    note: str = ""


def _layer_of(trial_id):
    for d, layer in (
        (REVIEW_DIR, "needs_review"),
        (MAPPED_DIR, "mapped"),
        (REVIEWED_DIR, "reviewed"),
    ):
        p = os.path.join(d, f"{trial_id}.yaml")
        if os.path.exists(p):
            return p, layer
    raise SystemExit(f"{trial_id}: not found in {REVIEW_DIR}, {MAPPED_DIR} or {REVIEWED_DIR}")


def _as_list(value):
    """
    A flag value as a list of names in the order the file gives them: a list,
    or a string joined with '; '. Duplicates dropped. Iterate this, not
    _as_set: a set's order follows PYTHONHASHSEED, so a sheet listed the
    same trial's genes in a different order on every run.
    """
    if isinstance(value, list):
        names = [str(v) for v in value]
    else:
        names = [v.strip() for v in str(value).split(";") if v.strip()] if value else []
    return list(dict.fromkeys(names))


def _as_set(value):
    """A flag value as a set of names, for membership tests."""
    return set(_as_list(value))
