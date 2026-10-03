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
    "diagnosis_over_generated",
    "diagnosis_excluded",
    "genomic_contradiction",
    "genomic_emptied",
    "remap_dropped_diagnoses",
    "gene_status_contradiction",
    "protein_change_unverified",
    "protein_change_check",
    "fusion_partner_unverified",
    "age_units_implausible",
    "diagnosis_seed_suspect",
    "gene_scope_suspect",
    "age_registry_conflict",
    "arm_narrower_than_step",
)


WILDCARDS = {"_SOLID_", "_LIQUID_"}


ADVICE = {
    "no_diagnosis": "No diagnosis: as it stands the trial matches every patient. Add "
    "oncotree_primary_diagnosis entries, or _SOLID_ / _LIQUID_ for a basket trial.",
    "gene_unsupported": "The model returned a gene the text scan did not find. If the text requires it, "
    "delete the `gene_unsupported:` line; if not, delete the whole genomic criterion.",
    "diagnosis_over_generated": "The diagnosis call answered with its own candidate list, which is a "
    "non-answer: the diagnoses describe the Oncotree branch, not this trial's population. "
    "As it stands the trial matches every patient in the branch. Cut the list to the "
    "populations the eligibility text states - the trial's own conditionsModule terms are "
    "the floor - then delete the top-level `diagnosis_over_generated:` line.",
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
    "arm_narrower_than_step": "A patient must satisfy the step's criteria and one arm's. These step "
    "diagnoses are admitted by no open arm, so the step and its arms disagree. Either an arm "
    "is too narrow (patients the trial enrols cannot match: add the diagnoses to their arm, "
    "or drop the arm's diagnosis criterion if the arm is for every population), or the step "
    "is too broad (remove the diagnoses the trial does not enrol). Then delete the top-level "
    "`arm_narrower_than_step:` line.",
    "age_registry_conflict": "The registry's minimumAge/maximumAge contradict the ages the eligibility text "
    "states (an adult trial capped at 18, a minimum of 14 against '18 or older'). The "
    "published bounds are the registry's. Set age_numerical to what the trial enrols, then "
    "delete the top-level `age_registry_conflict:` line.",
    "gene_scope_suspect": "A gene is required of every patient, but the inclusion text gives it for one "
    "cohort, phase or stratum, or as one route beside routes that need no alteration "
    "(MRD, immunophenotype, another diagnosis). Move the criterion into the arm it "
    "belongs to, put it in an OR with the other routes, or remove it; then delete the "
    "top-level `gene_scope_suspect:` line.",
    "gene_encoding_fixed": "Information, not a flag: the mapper rewrote a gene criterion by rule (an ITD "
    "also written as a mutation, an exclusion narrowed to the one protein change the "
    "text names, or a medulloblastoma subgroup removed as a gene). Check the change "
    "only if the text says otherwise.",
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
    "genomic_emptied": "The model returned these genes and post-processing dropped every one, so the "
    "trial now matches on its clinical criteria alone - every patient with the "
    "diagnosis, whatever their sequencing says. Usual causes: the alteration was "
    "written into hugo_symbol ('BRAF V600E'), a fusion was written as a pair, no "
    "variant_category was given, or the symbol is not in ref/genes.txt. Add the "
    "criterion the text states, or confirm the trial has none, then delete the "
    "top-level `genomic_emptied:` line.",
    "protein_change_unverified": "The stated protein change does not match the reference protein. Write the "
    "correct change as `protein_change:` (it is re-checked), or drop it; then "
    "delete `protein_change_unverified:` and `protein_change_check:`.",
    "fusion_partner_unverified": "The fusion partner is not an official gene symbol. Replace the line with "
    "`fusion_partner: <symbol>` or delete it.",
    "diagnosis_seed_suspect": "The diagnosis scope rests on something deterministic code distrusts: "
    'either a basket built on a specialty word ("Oncology" is not a population, so '
    "_SOLID_/_LIQUID_ may be far wider than the trial), or a B-lineage criterion on a "
    "trial whose text names only T-lineage disease (Oncotree has no lineage-free ALL "
    "node, so unqualified ALL maps to B-ALL). Decide from the text: narrow the wildcards "
    "to the diagnoses the trial enrols, or replace the B-lineage entry with the T-lineage "
    "one - or keep it if the trial really does enrol both. Then delete the top-level "
    "`diagnosis_seed_suspect:` line.",
    "age_units_implausible": "The registry's structured age fields are in days, weeks or months while the "
    "inclusion text states the same numbers in years, so one of the two is a "
    "sponsor error (and the trial may not be paediatric at all despite its CHILD "
    "tag). Decide which the protocol means: correct `age_numerical` to the years "
    "reading, or leave it if the registry is right. Then delete the top-level "
    "`age_units_implausible:` line. If the trial does not enrol children, exclude "
    "it with `review_helper exclude` instead.",
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
