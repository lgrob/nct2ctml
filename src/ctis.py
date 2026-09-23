"""
Map a CTIS (EU Clinical Trials Information System) record to MatchMiner CTML.

CTIS publishes a different document shape from ClinicalTrials.gov - everything
hangs off authorizedApplication.authorizedPartI - so the field accessors here
are CTIS-specific. Everything downstream of "get the criteria text out" is
not: diagnosis mapping, gene extraction, contradiction resolution and
biomarker status all reuse the functions in clinical_trials_gov, so both
sources get identical treatment once the text is in hand.

Two things CTIS does differently, and they are not merely cosmetic:

  * Criteria arrive as a list of separately labelled items, not one blob.
    The labels ("Specific for IEM arm:", "Meeting SR criteria:") carry
    per-cohort structure that ClinicalTrials.gov does not expose. They are
    preserved in the joined text rather than stripped.

  * Ages are EU category codes, not "6 Months" strings. The codes give the
    coarse Children/Adults/All label; a numeric bound is read from the
    criteria text when it states one, and omitted when it does not, rather
    than invented from the code.
"""
import re
from typing import Dict, List, Optional, Tuple

from loguru import logger

import src.clinical_trials_gov as ctg
import src.ctml_schema as cs
import src.match_criteria_mapper as mcm
import utils.age_bounds as ab

# CTIS ageRangeCategoryCode. Code 2 is the paediatric bucket - the same code
# the pull stage filters on (trial_config.ctis_age_group_codes).
AGE_CAT_PAEDIATRIC = "2"
AGE_CAT_ADULT = "3"
AGE_CAT_ELDERLY = "4"


def _g(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _part_one(trial_data: dict) -> dict:
    return _g(trial_data, "authorizedApplication", "authorizedPartI") or {}


def get_ct_number(trial_data: dict) -> str:
    return (trial_data.get("ctNumber")
            or _g(_part_one(trial_data), "trialDetails", "clinicalTrialIdentifiers", "ctNumber")
            or "")


def get_titles(trial_data: dict) -> Tuple[str, str]:
    ids = _g(_part_one(trial_data), "trialDetails", "clinicalTrialIdentifiers") or {}
    full = (ids.get("fullTitle") or "").strip()
    public = (ids.get("publicTitle") or "").strip()
    return (public or full), (full or public)


def get_conditions(trial_data: dict) -> List[str]:
    out = []
    for mc in _part_one(trial_data).get("medicalConditions") or []:
        t = (mc.get("medicalCondition") or "").strip()
        if t and t not in out:
            out.append(t)
    return out


def split_inclusion_exclusion_criteria(trial_data: dict) -> Tuple[str, str]:
    """
    Join CTIS's labelled criteria items into inclusion and exclusion text.

    Each item's label is kept inline. CTIS states which cohort or arm a
    criterion belongs to, and that is exactly the information the CTML match
    tree loses when alternative cohorts get flattened - so it is handed to the
    model rather than discarded.
    """
    ec = _g(_part_one(trial_data), "trialDetails", "trialInformation", "eligibilityCriteria") or {}

    def join(key: str) -> str:
        seen, lines = set(), []
        for item in ec.get(key) or []:
            text = re.sub(r"\s+", " ", (item.get(key) or "")).strip()
            if text and text not in seen:
                seen.add(text)
                lines.append(f"{item.get('number', len(lines) + 1)}. {text}")
        return "\n".join(lines)

    return join("principalInclusionCriteria"), join("principalExclusionCriteria")


def map_age_group(trial_data: dict) -> str:
    """Coarse CTML age label from the EU age-range category codes."""
    pop = _g(_part_one(trial_data), "trialDetails", "trialInformation", "populationOfTrialSubjects") or {}
    codes = {str(a.get("ageRangeCategoryCode") or a.get("ageRangeCategory") or "")
             for a in (pop.get("ageRanges") or [])}
    paed = AGE_CAT_PAEDIATRIC in codes
    adult = bool(codes & {AGE_CAT_ADULT, AGE_CAT_ELDERLY})
    if paed and adult:
        return "All"
    if paed:
        return "Children"
    if adult:
        return "Adults"
    return "All"


def map_age_numerical(ct_number: str, inclusion_text: str) -> List[str]:
    """
    The trial's age bounds as CTML age_numerical strings, lower first.

    ClinicalTrials.gov publishes structured ages; CTIS does not, so the model
    reads them from the criteria text. A pattern was tried first and rejected:
    across the 331 cached records it missed 162 that do state an age, because
    the phrasings vary too much ("Age >=1 and <80 years", "Patients aged 1 to
    <=21 years", "Children between 1 year (>= 12 months) and 18 years of
    age"). Loosening it far enough to catch those also caught the
    Karnofsky/Lansky split at 16 years, which is not an eligibility bound - a
    false minimum silently narrows who the trial can match.

    Only the minimum used to be read, so every CTIS trial was open-ended at
    the top: an adolescent trial matched adults. Both bounds now come from one
    call, at the same cost; the rules are in utils/age_bounds.py.

    Returns [] when no age is stated. An absent bound is correct; an invented
    one is not.
    """
    minimum, maximum = ab.prose_bounds(ab.read_age_bounds(f"CTIS: {ct_number}", inclusion_text),
                                       f"CTIS: {ct_number}")
    return [b for b in (minimum, maximum) if b]


def map_ctml_general_fields(trial_schema: dict, trial_data: dict) -> dict:
    p1 = _part_one(trial_data)
    short_title, long_title = get_titles(trial_data)
    ct = get_ct_number(trial_data)
    sponsors = [s.get("organisation", {}).get("name") for s in (p1.get("sponsors") or [])]
    sponsors = [s for s in sponsors if s]
    sponsor = sponsors[0] if sponsors else "NA"

    # CTML has no field for a non-NCT registry, so the CTIS number goes in
    # nct_id. matchminer-admin keys insert-vs-update off it, and leaving it
    # empty would make every reload insert a duplicate.
    trial_schema["nct_id"] = ct
    trial_schema["protocol_ids"] = [ct]
    trial_schema["short_title"] = short_title[:200]
    trial_schema["long_title"] = long_title[:500]
    trial_schema["phase"] = "NA"
    trial_schema["age"] = map_age_group(trial_data)
    trial_schema["principal_investigator"] = "NA"
    trial_schema["principal_investigator_institution"] = sponsor
    trial_schema["sponsor_list"] = {"sponsor": [{
        "is_principal_sponsor": "Y", "sponsor_name": sponsor,
        "sponsor_protocol_no": "", "sponsor_roles": "sponsor"}]}
    trial_schema["drug_list"] = {"drug": [
        {"drug_name": (p.get("productName") or p.get("name") or "NA")}
        for p in (p1.get("products") or [])][:12]}
    trial_schema["protocol_target_accrual"] = p1.get("rowSubjectCount") or 0
    trial_schema["study_start_date"] = trial_data.get("startDateEU")
    trial_schema["study_completion_date"] = trial_data.get("endDateEU")
    trial_schema["last_updated"] = (trial_data.get("publishDate") or "")[:10] or None
    trial_schema["summary"] = (
        _g(p1, "trialDetails", "trialInformation", "trialObjective", "mainObjective")
        or long_title)[:900]
    return trial_schema


def map_prior_treatment_requirements(trial_schema: dict, trial_data: dict) -> dict:
    inclusion, exclusion = split_inclusion_exclusion_criteria(trial_data)
    reqs = [l for l in inclusion.split("\n") if l.strip()]
    reqs += [f"Exclude - {l}" for l in exclusion.split("\n") if l.strip()]
    trial_schema["prior_treatment_requirements"] = reqs
    return trial_schema


def map_ctis_to_ctml(trial_data: dict,
                     gene_synonym_mapping: Dict[str, List[str]]) -> dict:
    """Map one CTIS record to a MatchMiner CTML document."""
    ct = get_ct_number(trial_data)
    trial_schema = cs.get_ctml_schema()
    trial_schema = map_ctml_general_fields(trial_schema, trial_data)
    trial_schema = map_prior_treatment_requirements(trial_schema, trial_data)

    inclusion_text, exclusion_text = split_inclusion_exclusion_criteria(trial_data)
    criteria = f"{inclusion_text}\n{exclusion_text}".strip()
    conditions = get_conditions(trial_data)
    # CTIS has no keyword list; the condition names are the closest equivalent
    # and are what the biomarker prompts key off.
    keywords = conditions

    clinical_criteria = {}

    logger.info(f"CTIS: {ct} | Mapping diagnosis to oncotree terms")
    # Seeded from the conditions exactly as the ClinicalTrials.gov path is.
    # This used to call map_eligibility_criteria_to_oncotree_term directly with
    # no seed, which left CTIS without the deterministic floor, without the
    # branch forcing that keeps a wrong level_1 from making the right answer
    # unreachable, and without any signal when the model dropped a diagnosis
    # the trial names outright. 61 of the 331 cached CTIS trials resolve from
    # their conditions alone, and every one of them was being left to the model.
    diagnosis_text = "\n".join(conditions + [criteria])
    seeded, from_eligibility = ctg.seed_and_map_diagnosis(ct, conditions, diagnosis_text)
    diagnoses = sorted(set(seeded) | set(from_eligibility))

    if not diagnoses:
        # Same fallback shape as ClinicalTrials.gov, minus the keyword and
        # title stage: CTIS registers neither. A trial whose conditions say
        # only "solid tumour" is a basket, and _SOLID_/_LIQUID_ is how CTML
        # says so - CTIS trials were previously unable to express that at all.
        diagnoses = sorted(ctg.basket_wildcards(conditions, ct))

    if diagnoses:
        clinical_criteria["oncotree_primary_diagnosis"] = diagnoses
    else:
        # Not an exception, for the reason given in clinical_trials_gov: a
        # trial missing from MatchMiner is the one failure a reviewer cannot
        # see. Mapping continues, and trial_map_manager._destination_for now
        # routes the result to the review queue - which it did not do for CTIS
        # until this change.
        logger.error(
            f"CTIS: {ct} | NEEDS REVIEW: no Oncotree diagnosis could be determined "
            f"from the eligibility criteria or the conditions {conditions}. Mapping "
            f"continues without a diagnosis criterion; a human must supply one."
        )

    age_numerical = map_age_numerical(ct, inclusion_text)
    if age_numerical:
        clinical_criteria["age_numerical"] = age_numerical
    else:
        logger.info(f"CTIS: {ct} | No numeric age stated in criteria; leaving age_numerical unset")

    clinical_criteria.update(
        ctg._map_biomarker_statuses(ct, criteria, keywords, level="global"))

    logger.info(f"CTIS: {ct} | Mapping genomic criteria")
    genomic_ctml = ctg.map_ctml_match_genomic_criteria(
        ct, gene_synonym_mapping, inclusion_text, exclusion_text)

    clinical_ctml = mcm.convert_to_ctml_clinical_schema(clinical_criteria)
    match_result = mcm.combine_clinical_and_genomic_ctml(clinical_ctml, genomic_ctml)

    step = (trial_schema.get("treatment_list") or {}).get("step") or [{}]
    step[0]["match"] = [match_result] if match_result else []
    step[0].setdefault("step_internal_id", 1)
    step[0].setdefault("step_code", "1")
    step[0].setdefault("step_type", "Registration")
    # CTIS does not publish per-arm eligibility the way ClinicalTrials.gov
    # armGroups does, so criteria stay at step level rather than being split
    # across arms that would be guesses.
    step[0]["arm"] = [{
        "arm_code": "Registration", "arm_internal_id": 0,
        "arm_description": "CTIS record: no per-arm eligibility published.",
        "arm_suspended": "N", "dose_level": []}]
    trial_schema["treatment_list"] = {"step": step}

    unsat = mcm.find_unsatisfiable_genes(match_result) if match_result else []
    if unsat:
        logger.warning(f"CTIS: {ct} | Unsatisfiable genomic tree for {unsat}; needs review")

    return trial_schema
