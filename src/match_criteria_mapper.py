# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

from typing import Dict, TypedDict

import re

from loguru import logger

import config
import utils.aho_corasick as ac
import src.trial_data_helper as tdh
from utils.genomic_patterns import _ACCEPTABLE_PROTEIN_CHANGE_PATTERNS
from utils.reference_validation import filter_diagnoses, filter_genomic_criteria


class ArmCriteriaText(TypedDict, total=False):
    """
    Textual eligibility snippets for a single CTML arm.

    Each arm (and the special global block) can contribute:
    - inclusion_text: text that specifies inclusion criteria for this arm only.
    - exclusion_text: text that specifies exclusion criteria for this arm only.

    Callers SHOULD store empty strings when there is no arm-specific text, so
    downstream code can safely concatenate strings without additional None checks.
    """

    inclusion_text: str
    exclusion_text: str

    def get_combined_eligibility_text(self) -> str:
        """
        Combine inclusion and exclusion text into a single eligibility criteria string.

        The combined text is in the format:
        "Inclusion Criteria: {inclusion_text}\nExclusion Criteria: {exclusion_text}"
        """
        combined_text = ""
        if self.get("inclusion_text"):
            combined_text += f"Inclusion Criteria: {self['inclusion_text']}\n"
        if self.get("exclusion_text"):
            combined_text += f"Exclusion Criteria: {self['exclusion_text']}"
        return combined_text.strip()


ArmCriteriaBlocks = Dict[str, ArmCriteriaText]
"""
Normalized arm-level eligibility criteria, keyed by CTML arm identifier.

Keys:
- \"global\": criteria that apply to all arms in the trial.
- \"<arm_key>\": one entry per CTML arm, where arm_key is a stable identifier
  that can be mapped back to the CTML arm definition (for example, an internal
  arm ID or the CTML arm_code).

Example shape:

    arm_criteria_blocks: ArmCriteriaBlocks = {
        \"global\": {
            \"inclusion_text\": \"... applies to all arms ...\",
            \"exclusion_text\": \"... applies to all arms ...\",
        },
        \"ARM_A\": {
            \"inclusion_text\": \"... only for arm A ...\",
            \"exclusion_text\": \"\",
        },
        \"ARM_B\": {
            \"inclusion_text\": \"\",
            \"exclusion_text\": \"... only for arm B ...\",
        },
    }
"""


def _clean_protein_change_fields(genomic_criteria: list) -> list:
    """
    Clean up protein_change-related fields on genomic criteria in place.

    - Drop protein_change when null/empty (do not emit `protein_change: null` in YAML).
    - Remove protein_change fields that do not match any acceptable pattern.
    - If protein_change ends with X/x (e.g. p.G719X), move it to wildcard_protein_change.
    """
    if not genomic_criteria:
        return genomic_criteria

    for alteration in genomic_criteria:
        genomic = alteration.get("genomic")
        if not isinstance(genomic, dict):
            continue

        if "protein_change" not in genomic:
            continue

        protein_change = genomic.get("protein_change")
        # Remove null/empty so YAML never serializes `protein_change: null`
        if protein_change is None or str(protein_change).strip() == "" or str(protein_change).strip().lower() == "null":
            genomic.pop("protein_change", None)
            continue

        protein_change_str = str(protein_change).strip()

        # Handle wildcard protein changes, e.g. p.G719X
        if protein_change_str.upper().endswith("X"):
            genomic.pop("protein_change", None)
            genomic["wildcard_protein_change"] = protein_change_str.strip("X")
            continue

        # Remove incorrect protein_change values that do not match acceptable patterns
        if not any(pattern.match(protein_change_str) for pattern in _ACCEPTABLE_PROTEIN_CHANGE_PATTERNS):
            genomic.pop("protein_change", None)

    return genomic_criteria


def _postprocess_genomic_criteria(genomic_criteria: list, trial_id: str = "") -> list:
    """
    Post-process genomic criteria:

    - Normalize HUGO symbols.
    - Drop criteria naming a gene that does not exist.
    - Clean protein_change /  fields.
    """
    if not genomic_criteria:
        return genomic_criteria

    # Normalize HUGO symbols as part of post-processing
    genomic_criteria = tdh.update_hugo_symbol(genomic_criteria)
    # update_hugo_symbol only rewrites HER2 to ERBB2, so this is where retired
    # symbols are brought up to date and unrecognised ones are dropped. Dropping
    # beats keeping: an invented symbol matches no patient, so it silently
    # narrows the arm rather than failing visibly.
    genomic_criteria = filter_genomic_criteria(genomic_criteria, trial_id)
    genomic_criteria = _clean_protein_change_fields(genomic_criteria)

    return genomic_criteria

def get_keywords_from_conditions(conditions_list):
    all_keywords = set()
    for cond in conditions_list:
        cond_keywords = [word for part in cond.split(',') for word in part.split() if word]
        for cond_keyword in cond_keywords:
            if cond_keyword.lower() not in config.keywords_to_remove:
                all_keywords.add(cond_keyword)
    return all_keywords

def convert_to_ctml_clinical_schema(clinical_critera, trial_id: str = "") -> dict:
    clinical_critera = dict(clinical_critera or {})

    # Extract the diagnosis list
    diagnoses = []
    if "oncotree_primary_diagnosis" in clinical_critera and clinical_critera["oncotree_primary_diagnosis"]:
        raw_diagnoses = clinical_critera.pop("oncotree_primary_diagnosis")
        if not isinstance(raw_diagnoses, list):
            raw_diagnoses = [raw_diagnoses]
        # Rewrite Oncotree codes to display names and drop terms absent from the
        # tree. If that empties the list, fall through to the no-diagnosis path
        # below rather than emitting a clinical block keyed on a string that can
        # never match a patient.
        diagnoses = filter_diagnoses(raw_diagnoses, trial_id)

    if diagnoses:
        if len(diagnoses) > 1:  # incase of multiple diagnoses, put the result under 'or' operator
            diagnosis_result = {"or": []}
            for diagnosis in diagnoses:
                diagnosis_ctml = {"clinical": {"oncotree_primary_diagnosis": diagnosis}}
                diagnosis_result["or"].append(diagnosis_ctml)

            # Only use an 'and' operator if there are other clinical criteria besides diagnoses
            other_clinical_criteria = {
                k: v
                for k, v in clinical_critera.items()
                if v is not None and v != "" and v != [] and v != {}
            }
            if other_clinical_criteria:
                return {"and": [diagnosis_result, {"clinical": {**other_clinical_criteria}}]}
            return diagnosis_result

        clinical_ctml = {
            "clinical": {
                **clinical_critera,  # Add all other keys
                "oncotree_primary_diagnosis": diagnoses[0],  # Add the only diagnosis
            }
        }
        return clinical_ctml

    if not clinical_critera:
        return {}
    return {"clinical": clinical_critera}


# Checks that the genomic crietria returned by AI model is not empty and has "hugo_symbol", "variant_category" keys
def _negated(variant_category: str) -> bool:
    return (variant_category or "").startswith("!")


def _base_category(variant_category: str) -> str:
    return (variant_category or "").lstrip("!").strip().lower()


# Wording in the inclusion text that signals genuine alternative cohorts,
# i.e. the trial enrols patients both with and without the alteration.
_COHORT_NEGATION_CUES = (
    "without", "non-amplified", "not amplified", "negative for", "absence of",
    "lack of", "wild-type", "wildtype", "wild type", "non-mutated", "unmutated",
)


def _text_mentions_gene(text: str, gene: str) -> bool:
    """
    Is the symbol actually written in this text?

    Boundaries are non-alphanumeric rather than \b so that a symbol inside a
    fusion name still counts - ABL1 in "BCR-ABL1" is a mention - while short
    symbols do not match inside ordinary words (AR in "are", MET in "metastatic").
    """
    if not text or not gene:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(gene)}(?![A-Za-z0-9])",
                     text, re.IGNORECASE) is not None


def resolve_contradictory_genes(inclusions: list, exclusions: list,
                                inclusion_text: str = "",
                                exclusion_text: str = "") -> tuple[list, list, list]:
    """
    Reconcile genes that are required and forbidden at the same time.

    Inclusions are OR-ed and exclusions AND-ed, then the two are AND-ed, so a
    gene on both sides makes the tree unsatisfiable: the trial matches nobody,
    silently. There are two quite different causes, and they need opposite
    treatment.

    1. A spurious exclusion. Oncology disease names embed gene names -
       "H3 K27M-mutant diffuse glioma", "BCR-ABL positive ALL",
       "EGFR-mutant NSCLC" - so a disease mention inside an unrelated
       exclusion (say a prior-therapy rule) gets misread as a genomic
       exclusion. Observed on NCT05580562, where "since the initial diagnosis
       of H3 K27M-mutant diffuse glioma" in a bevacizumab exclusion produced
       H3F3B !Any Variation. Here the inclusion is right and the exclusion is
       an artefact, so only the exclusion is dropped. This is the common case,
       because disease-name-contains-gene-name is ubiquitous.

    2. Genuine alternative cohorts. The inclusion text itself negates the
       gene, e.g. SIOPEN high-risk neuroblastoma: "stage 2, 3, 4, 4s WITH MYCN
       amplification, or stage 4 WITHOUT MYCN amplification". Both cohorts
       enrol, so the net requirement on that gene is none and both sides go.
       The two-level CTML shape cannot express per-cohort criteria, so this
       loses the cohort distinction either way; dropping both at least keeps
       the trial matchable rather than matching nobody.

    3. A fabricated inclusion. The gene is absent from the inclusion text and
       present in the exclusion text, so the exclusion is the criterion the
       trial actually states and the inclusion is invented. Observed on
       NCT03643276, a front-line ALL protocol whose only mention of the gene
       is the exclusion "Ph+ (BCR-ABL1 or t(9;22)-positive) ALL". Treating
       that as case 1 kept a hallucinated ABL1 requirement and discarded a
       genuine exclusion, so a Ph+ patient would have matched a trial that
       explicitly excludes them. Here the inclusion is dropped and the
       exclusion kept.

    Case 3 requires positive evidence from the exclusion text, not merely the
    absence of evidence in the inclusion text. Checking only the inclusion
    text was wrong for every gene the model infers from variant nomenclature
    rather than a symbol: "H3 K27M-mutant diffuse glioma" names no H3 symbol,
    so a correct H3-3A inclusion looked fabricated, and no alias rescues it -
    none of H3-3A's aliases is the bare string "H3". When the symbol is in
    neither text there is nothing to weigh, and case 1 is assumed, as it is
    when no text is available at all: it is the commoner case and the safer
    error.

    Returns (inclusions, exclusions, notes) where notes describes what was
    dropped and why, for the manual review step.
    """
    def gene_of(alteration):
        return (alteration.get("genomic", {}) or {}).get("hugo_symbol")

    contradictory = []
    for inc in inclusions:
        gene = gene_of(inc)
        if not gene:
            continue
        inc_cat = _base_category((inc.get("genomic", {}) or {}).get("variant_category"))
        for exc in exclusions:
            if gene_of(exc) != gene:
                continue
            exc_cat = _base_category((exc.get("genomic", {}) or {}).get("variant_category"))
            # "!Any Variation" negates every alteration in the gene, so it
            # contradicts any positive requirement on it; otherwise the
            # categories have to match to contradict.
            if exc_cat in ("any variation", inc_cat):
                contradictory.append(gene)
                break

    if not contradictory:
        return inclusions, exclusions, []

    text = (inclusion_text or "").lower()
    cohort_genes, artefact_genes, fabricated_genes = set(), set(), set()
    for gene in sorted(set(contradictory)):
        stated_in_inclusion = _text_mentions_gene(inclusion_text, gene)
        stated_in_exclusion = _text_mentions_gene(exclusion_text, gene)
        if inclusion_text and not stated_in_inclusion and stated_in_exclusion:
            # Absent where it is required, present where it is forbidden: the
            # exclusion is what the trial states and the inclusion is invented.
            fabricated_genes.add(gene)
        elif any(cue in text for cue in _COHORT_NEGATION_CUES):
            cohort_genes.add(gene)
        else:
            artefact_genes.add(gene)

    notes = []
    for gene in sorted(artefact_genes):
        logger.warning(
            f"Contradictory genomic criteria for {gene}: required and excluded in the "
            f"same match tree. The inclusion text does not negate {gene}, so the "
            f"exclusion is most likely a disease-name mention misread as a genomic "
            f"exclusion. Keeping the inclusion and dropping the exclusion."
        )
        notes.append(f"{gene}: dropped spurious exclusion")
    for gene in sorted(cohort_genes):
        logger.warning(
            f"Contradictory genomic criteria for {gene}: required and excluded in the "
            f"same match tree, which matches no patient. The inclusion text negates "
            f"{gene}, so the trial enrols alternative cohorts with and without the "
            f"alteration; its net requirement is none. Dropping both constraints. "
            f"Flag for manual review - the cohort distinction cannot be expressed."
        )
        notes.append(f"{gene}: dropped both (alternative cohorts)")

    for gene in sorted(fabricated_genes):
        logger.warning(
            f"Contradictory genomic criteria for {gene}: required and excluded in the "
            f"same match tree, but {gene} appears only in the exclusion text. "
            f"The inclusion is fabricated and the exclusion is the real criterion. "
            f"Dropping the inclusion and keeping the exclusion."
        )
        notes.append(f"{gene}: dropped fabricated inclusion")

    drop_inc = cohort_genes | fabricated_genes
    drop_exc = cohort_genes | artefact_genes
    keep_inc = [a for a in inclusions if gene_of(a) not in drop_inc]
    keep_exc = [a for a in exclusions if gene_of(a) not in drop_exc]
    return keep_inc, keep_exc, notes


def find_unsatisfiable_genes(match_node) -> list:
    """
    Report genes that a match tree both requires and forbids under an 'and'.

    A defence-in-depth check over the finished tree, independent of how it was
    assembled, so a contradiction introduced anywhere still gets surfaced.
    """
    findings: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "and" in node and isinstance(node["and"], list):
                positive, negative = {}, {}
                def collect(n):
                    if isinstance(n, dict):
                        if "genomic" in n and isinstance(n["genomic"], dict):
                            g = n["genomic"].get("hugo_symbol")
                            c = n["genomic"].get("variant_category")
                            if g:
                                (negative if _negated(c) else positive).setdefault(
                                    g, set()).add(_base_category(c))
                        for k in ("and", "or"):
                            if isinstance(n.get(k), list):
                                for child in n[k]:
                                    collect(child)
                for branch in node["and"]:
                    collect(branch)
                for gene, neg_cats in negative.items():
                    pos_cats = positive.get(gene)
                    if not pos_cats:
                        continue
                    if "any variation" in neg_cats or (neg_cats & pos_cats):
                        findings.append(gene)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(match_node)
    return sorted(set(findings))


def convert_to_ctml_genomic_schema(inclusion_genomic_criteria: list, exclusion_genomic_criteria: list,
                                   inclusion_text: str = "", exclusion_text: str = "",
                                   trial_id: str = "") -> dict: 
    inclusions = []
    exclusions = []
    print(tdh.get_all_keys(inclusion_genomic_criteria))
    print(tdh.get_all_keys(exclusion_genomic_criteria))
    if inclusion_genomic_criteria and all(key in tdh.get_all_keys(inclusion_genomic_criteria) for key in ["hugo_symbol", "variant_category"]):
        # post processing
        inclusion_genomic_criteria = _postprocess_genomic_criteria(inclusion_genomic_criteria, trial_id)
        for alteration in inclusion_genomic_criteria:
            variant_category = alteration["genomic"]["variant_category"]
            # if variant_category begins with !, add alteration to exclusions, without removing !
            if variant_category.startswith('!'):
                if alteration not in exclusions:
                    exclusions.append(alteration)
            else:
                if alteration not in inclusions:
                    inclusions.append(alteration)
    
    if exclusion_genomic_criteria and all(key in tdh.get_all_keys(exclusion_genomic_criteria) for key in ["hugo_symbol", "variant_category"]):
        # post processing
        exclusion_genomic_criteria = _postprocess_genomic_criteria(exclusion_genomic_criteria, trial_id)
        for alteration in exclusion_genomic_criteria:
            if alteration not in exclusions:
                exclusions.append(alteration)

    inclusions, exclusions, contradiction_notes = resolve_contradictory_genes(
        inclusions, exclusions, inclusion_text, exclusion_text)
    if contradiction_notes:
        print(f"Contradictory gene constraints resolved: {contradiction_notes}")

    #combine inclusions with a top level 'or' and exclusions with a top level 'and'
    if inclusions:
        if len(inclusions) == 1:
            inclusion_genomic_criteria_ctml = inclusions[0]
        else:
            inclusion_genomic_criteria_ctml = {"or": inclusions}
    else:
        inclusion_genomic_criteria_ctml = {}

    print(f'inclusion_genomic_criteria_ctml: {inclusion_genomic_criteria_ctml}')

    if exclusions:
        if len(exclusions) == 1:
            exclusion_genomic_criteria_ctml = exclusions[0]
        else:
            exclusion_genomic_criteria_ctml = {"and": exclusions}
    else:
        exclusion_genomic_criteria_ctml = {}

    print(f'exclusion_genomic_criteria_ctml: {exclusion_genomic_criteria_ctml}')

    #combine both inclusion and exclusion criteria under a top level 'and'
    if inclusion_genomic_criteria_ctml and exclusion_genomic_criteria_ctml:
        inclusion_exclusion_genomic_criteria_ctml = {"and": [inclusion_genomic_criteria_ctml, exclusion_genomic_criteria_ctml]}
        return inclusion_exclusion_genomic_criteria_ctml
    elif inclusion_genomic_criteria_ctml:
        return inclusion_genomic_criteria_ctml
    elif exclusion_genomic_criteria_ctml:
        return exclusion_genomic_criteria_ctml
    return {}

def combine_clinical_and_genomic_ctml(clinical_ctml, genomic_ctml):
    if clinical_ctml and len(clinical_ctml) > 0  \
        and genomic_ctml and len(genomic_ctml) > 0:
        match_result = {"and": []} 
        match_result["and"].append(clinical_ctml)
        match_result["and"].append(genomic_ctml)
        logger.debug(f"combined clinical and genomic CTML: {match_result}")
        return match_result
    elif clinical_ctml and len(clinical_ctml) > 0 :
        match_result = clinical_ctml
        logger.debug(f"using only clinical CTML: {match_result}")
        return match_result
    else:
        match_result = genomic_ctml
        logger.debug(f"using only genomic CTML: {match_result}")
        return match_result

def check_if_eligibility_criteria_contains_gene_info(genes:list, eligibility):
    print("looking for gene keywords")
    contains = ac.search_keywords_in_text(genes, eligibility)
    return contains

def check_if_eligibility_criteria_contains_pdl1_info(nct_keywords:list, eligibility):
    pdl1_keywords_to_check = ['pdl1', 'pd-l1']
    nct_keywords_string = ', '.join(nct_keywords)
    print("looking for PDL1 keywords")
    contains = ac.search_keywords_in_text(pdl1_keywords_to_check, nct_keywords_string)
    if contains:
        return True
    else:
        contains = ac.search_keywords_in_text(pdl1_keywords_to_check, eligibility)
        return contains
    
def check_if_eligibility_criteria_contains_mmr_info(nct_keywords:list, eligibility):
    mmr_keywords_to_check = ['mmr', 'Mismatch Repair', 'msi', 'msi-h','dMMR','msi-l','MSI-high','MSI-low']
    nct_keywords_string = ', '.join(nct_keywords)
    print("looking for MMR keywords")
    contains = ac.search_keywords_in_text(mmr_keywords_to_check, nct_keywords_string)
    if contains:
        return True
    else:
        contains = ac.search_keywords_in_text(mmr_keywords_to_check, eligibility)
        return contains