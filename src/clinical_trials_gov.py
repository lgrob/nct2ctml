# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

"""
This script contains methods that deal with extraction and manipulation
of data from clinicaltrials.gov
"""

import json
import re

from loguru import logger

import src.ctml_schema as cs
import src.mapping.biomarkers as biomarkers
import src.mapping.diagnosis as diagnosis
import src.mapping.genomic as genomic
import src.match_criteria_mapper as mcm
import src.trial_config as config
import src.trial_data_helper as tdh
import utils.age_bounds as ab
import utils.llm.prompts.arms as arm_prompts
import utils.llm.prompts.diagnosis as dx_prompts
import utils.oncotree as onct
from src.match_criteria_mapper import ArmCriteriaBlocks


def map_nct_to_ctml(trial_data: dict, gene_synonym_mapping: dict[str, list[str]]) -> dict:
    """
    Logic to map the fields from https://clinicaltrials.gov/ API response to the clinical trial schema required by matchminer
    Parameters
    ----------
    trial_data: dict
        Dictionary containing the response from https://clinicaltrials.gov/ API for a particular trial

    Returns
    -------
    trial_schema: dict
        Dictionary containing the keys and values for a trial as per the clinical trial schema for matchminer
    """

    trial_schema = cs.get_ctml_schema()

    trial_schema = map_ctml_general_fields(trial_schema, trial_data)

    trial_schema = map_prior_treatment_requirements(trial_schema, trial_data)

    all_arms_criteria = get_arm_criteria_blocks_for_trial(trial_data, trial_schema)
    logger.debug(f"arm_result JSON: {json.dumps(all_arms_criteria, indent=2, sort_keys=True)}")

    updated_trial_schema = map_nct_to_clinical_and_genomic_criteria(
        trial_data, all_arms_criteria, trial_schema, gene_synonym_mapping
    )

    logger.debug(
        f"CTML: After mapping clinical and genomic match criteria | {updated_trial_schema}"
    )

    return updated_trial_schema


def map_nct_to_clinical_and_genomic_criteria(
    trial_data: dict,
    all_arms_criteria: ArmCriteriaBlocks,
    trial_schema: dict,
    gene_synonym_mapping: dict[str, list[str]],
) -> dict:
    nct_id = get_nct_id(trial_data)

    global_nct_criteria = mcm.combined_eligibility_text(all_arms_criteria.get("global", {}))
    global_inclusion_text = all_arms_criteria.get("global", {}).get("inclusion_text", "")
    global_exclusion_text = all_arms_criteria.get("global", {}).get("exclusion_text", "")

    keywords = get_nct_keywords(trial_data)

    # map global clinical criteria

    mapped_global_clinical_critera = {}

    logger.info(f"NCTID: {nct_id} | Mapping global diagnosis to oncotree terms")
    import config

    mode = getattr(config, "DIAGNOSIS_INPUT", "legacy")
    ident = tdh.safe_get(trial_data, ["protocolSection", "identificationModule"]) or {}
    global_dx_text = diagnosis.diagnosis_text(
        global_inclusion_text,
        global_exclusion_text,
        # labelled keeps the NCT text as it was apart from the prompt rule:
        # these sections were already labelled.
        title=(ident.get("officialTitle") or ident.get("briefTitle") or "")
        if mode == "inclusion_only"
        else "",
        conditions=(
            tdh.safe_get(trial_data, ["protocolSection", "conditionsModule", "conditions"]) or []
        )
        if mode == "inclusion_only"
        else (),
        legacy=global_nct_criteria,
    )
    oncotree_diagnoses_list = map_global_diagnosis_to_oncotree_term(trial_data, global_dx_text)
    mapped_global_clinical_critera["oncotree_primary_diagnosis"] = oncotree_diagnoses_list

    # A list, because a trial can bound age at both ends. The converter emits
    # each bound as its own clinical node - two age_numerical keys cannot live
    # in one dict, and MatchMiner intersects sibling nodes anyway.
    # The full inclusion text, not the global slice: the prose reading takes
    # the widest range across cohorts, so it needs to see every cohort.
    age_prose = ab.read_age_bounds(nct_id, split_inclusion_exclusion_criteria(trial_data)[0])
    age_bounds = map_age_numerical(trial_data, age_prose)
    if age_bounds:
        mapped_global_clinical_critera["age_numerical"] = age_bounds

    gender_str = map_gender(trial_data)
    if gender_str:
        mapped_global_clinical_critera["gender"] = gender_str

    logger.info(f"NCTID: {nct_id} | Mapping disease status")
    disease_status_dict = biomarkers.map_disease_status(nct_id, global_nct_criteria, keywords)
    if disease_status_dict and len(disease_status_dict.get("disease_status", {})) > 0:
        mapped_global_clinical_critera.update(disease_status_dict)

    biomarker_status_dict = biomarkers._map_biomarker_statuses(
        nct_id, global_nct_criteria, keywords, level="global"
    )
    mapped_global_clinical_critera.update(biomarker_status_dict)

    logger.debug(f"global clinical criteria: {mapped_global_clinical_critera}")
    global_clinical_ctml = mcm.convert_to_ctml_clinical_schema(
        mapped_global_clinical_critera, nct_id
    )

    # map global genomic criteria

    logger.info(f"NCTID: {nct_id} | Mapping global genomic criteria")
    global_genomic_ctml = genomic.map_ctml_match_genomic_criteria(
        nct_id, gene_synonym_mapping, global_inclusion_text, global_exclusion_text
    )
    trial_level_match_result = mcm.combine_clinical_and_genomic_ctml(
        global_clinical_ctml, global_genomic_ctml
    )
    match_list = trial_schema["treatment_list"]["step"][0]["match"]
    match_list.append(trial_level_match_result)

    # Defence in depth: a match tree that requires and forbids the same gene
    # matches no patient, and does so silently. Surface it for manual review.
    unsatisfiable = mcm.find_unsatisfiable_genes(trial_level_match_result)
    if unsatisfiable:
        logger.error(
            f"NCTID: {nct_id} | Trial-level match tree is unsatisfiable for "
            f"{', '.join(unsatisfiable)} - it will match no patient. Needs manual review."
        )

    _map_arm_level_matches(
        nct_id=nct_id,
        all_arms_criteria=all_arms_criteria,
        trial_schema=trial_schema,
        keywords=keywords,
        gene_synonym_mapping=gene_synonym_mapping,
    )
    return trial_schema


def _map_arm_level_matches(
    nct_id: str,
    all_arms_criteria: ArmCriteriaBlocks,
    trial_schema: dict,
    keywords: list,
    gene_synonym_mapping: dict[str, list[str]],
) -> None:
    # Handle conversion at arm level if there are arm specific criteria.
    for level_code, arm_criteria in all_arms_criteria.items():
        if level_code == "global":
            continue
        if arm_criteria["inclusion_text"] == "" and arm_criteria["exclusion_text"] == "":
            continue

        arm_eligibility_criteria = mcm.combined_eligibility_text(arm_criteria)
        arm_inclusion_text = arm_criteria.get("inclusion_text", "")
        arm_exclusion_text = arm_criteria.get("exclusion_text", "")
        mapped_arm_clinical_critera = {}

        logger.info(
            f"NCTID: {nct_id} | Mapping arm level diagnosis to oncotree terms for arm {level_code}"
        )
        oncotree_diagnoses_list = diagnosis.map_eligibility_criteria_to_oncotree_term(
            nct_id,
            diagnosis.diagnosis_text(
                arm_inclusion_text, arm_exclusion_text, legacy=arm_eligibility_criteria
            ),
        )
        if oncotree_diagnoses_list and len(oncotree_diagnoses_list) > 0:
            mapped_arm_clinical_critera["oncotree_primary_diagnosis"] = oncotree_diagnoses_list
        mapped_arm_clinical_critera.update(
            biomarkers._map_biomarker_statuses(
                nct_id=nct_id,
                eligibility_criteria=arm_eligibility_criteria,
                keywords=keywords,
                level=f"arm level for arm {level_code}",
            )
        )

        logger.debug(f"arm level clinical criteria: {mapped_arm_clinical_critera}")
        arm_clinical_ctml = mcm.convert_to_ctml_clinical_schema(mapped_arm_clinical_critera, nct_id)
        logger.debug(f"arm level clinical criteria as CTML: {arm_clinical_ctml}")

        logger.info(f"NCTID: {nct_id} | Mapping arm level genomic criteria for arm {level_code}")
        arm_genomic_ctml = genomic.map_ctml_match_genomic_criteria(
            nct_id, gene_synonym_mapping, arm_inclusion_text, arm_exclusion_text
        )
        arm_level_match_result = mcm.combine_clinical_and_genomic_ctml(
            arm_clinical_ctml, arm_genomic_ctml
        )
        if arm_level_match_result:
            for arm in trial_schema["treatment_list"]["step"][0]["arm"]:
                if arm["arm_code"] == level_code:
                    arm.setdefault("match", []).append(arm_level_match_result)


def get_arm_criteria_blocks_for_trial(
    trial_data: dict,
    trial_schema: dict,
) -> ArmCriteriaBlocks:
    """
    Helper to run the arm-level LLM mapper and normalization.

    This does NOT modify trial_schema; it just returns the normalized
    ArmCriteriaBlocks structure so callers can inspect or plug it into
    downstream mapping code.
    """
    nct_id = trial_data["protocolSection"]["identificationModule"]["nctId"]
    arm_groups = (
        tdh.safe_get(trial_data, ["protocolSection", "armsInterventionsModule", "armGroups"]) or []
    )
    inclusion_text, exclusion_text = split_inclusion_exclusion_criteria(trial_data)

    arm_mapping = arm_prompts.get_arm_criteria_mapping(
        nct_id=nct_id,
        arm_groups=arm_groups,
        inclusion_criteria=inclusion_text,
        exclusion_criteria=exclusion_text,
    )

    return build_arm_criteria_blocks(arm_mapping=arm_mapping, trial_schema=trial_schema)


def build_arm_criteria_blocks(
    arm_mapping: dict,
    trial_schema: dict,
) -> ArmCriteriaBlocks:
    """
    Normalize the LLM arm-mapper JSON into ArmCriteriaBlocks keyed by CTML arms.

    Args:
        arm_mapping:
            The JSON-like dict returned by ai.get_arm_criteria_mapping, with shape:
            {
              "global": {
                "inclusion_text": "...",
                "exclusion_text": "..."
              },
              "arms": [
                {
                  "arm_label": "<label from armGroups[i].label>",
                  "inclusion_text": "...",       # may be empty
                  "exclusion_text": "..."        # may be empty
                },
                ...
              ]
            }
        trial_schema:
            The partially populated CTML trial schema. We use the
            treatment_list.step[0].arm entries to determine CTML arm keys.
    """
    arm_mapping = arm_mapping or {}

    # Initialize the global block, defaulting to empty strings when missing.
    global_block = arm_mapping.get("global") or {}
    global_inclusion = global_block.get("inclusion_text") or ""
    global_exclusion = global_block.get("exclusion_text") or ""

    arm_criteria_blocks: ArmCriteriaBlocks = {
        "global": {
            "inclusion_text": global_inclusion,
            "exclusion_text": global_exclusion,
        }
    }

    # Build a lookup from arm_label -> per-arm text produced by the LLM.
    per_arm_list = arm_mapping.get("arms") or []
    label_to_text: dict[str, dict[str, str]] = {}
    for arm_entry in per_arm_list:
        if not isinstance(arm_entry, dict):
            continue
        arm_label = arm_entry.get("arm_label")
        if not isinstance(arm_label, str) or not arm_label:
            continue

        label_to_text[arm_label] = {
            "inclusion_text": arm_entry.get("inclusion_text") or "",
            "exclusion_text": arm_entry.get("exclusion_text") or "",
        }

    # Traverse CTML arms and attach any per-arm snippets using arm_code as key.
    ctml_arms = trial_schema.get("treatment_list", {}).get("step", [{}])[0].get("arm", [])

    for ctml_arm in ctml_arms:
        if not isinstance(ctml_arm, dict):
            continue

        ctml_arm_code = ctml_arm.get("arm_code")
        if not isinstance(ctml_arm_code, str) or not ctml_arm_code:
            # If arm_code is missing or malformed, skip attaching per-arm text.
            continue

        per_arm_text = label_to_text.get(
            ctml_arm_code, {"inclusion_text": "", "exclusion_text": ""}
        )

        arm_criteria_blocks[ctml_arm_code] = {
            "inclusion_text": per_arm_text.get("inclusion_text", ""),
            "exclusion_text": per_arm_text.get("exclusion_text", ""),
        }

    return arm_criteria_blocks


def map_ctml_general_fields(trial_schema, trial_data) -> dict:

    nct_id = trial_data["protocolSection"]["identificationModule"]["nctId"]

    try:
        trial_schema["nct_id"] = nct_id
        trial_schema["age"] = map_age_group(trial_data)
        trial_schema["long_title"] = trial_data["protocolSection"]["identificationModule"][
            "officialTitle"
        ]
        trial_schema["principal_investigator_institution"] = trial_data["protocolSection"][
            "identificationModule"
        ]["organization"]["fullName"]
        trial_schema["principal_investigator"] = (
            "NA"  # overwrriten later if a PI is found in overall officials list
        )

        phases = trial_data["protocolSection"]["designModule"]["phases"]
        trial_schema["phase"] = phases[0] if len(phases) > 0 else ""
        trial_schema["short_title"] = trial_data["protocolSection"]["identificationModule"][
            "briefTitle"
        ]
        trial_schema["summary"] = trial_data["protocolSection"]["descriptionModule"]["briefSummary"]
        trial_schema["protocol_target_accrual"] = trial_data["protocolSection"]["designModule"][
            "enrollmentInfo"
        ]["count"]
        trial_schema["sponsor_list"]["sponsor"].append(
            {
                "is_principal_sponsor": "Y",
                "sponsor_name": trial_data["protocolSection"]["sponsorCollaboratorsModule"][
                    "leadSponsor"
                ]["name"],
                "sponsor_protocol_no": "",
                "sponsor_roles": "sponsor",
            }
        )

        trial_schema["curated_on"] = trial_data["protocolSection"]["statusModule"][
            "studyFirstPostDateStruct"
        ]["date"]
        trial_schema["last_updated"] = trial_data["protocolSection"]["statusModule"][
            "lastUpdatePostDateStruct"
        ]["date"]

        start_date_struct = tdh.safe_get(
            trial_data, ["protocolSection", "statusModule", "startDateStruct"]
        )
        if start_date_struct and start_date_struct.get("type") == "ACTUAL":
            trial_schema["study_start_date"] = start_date_struct["date"]
        else:
            trial_schema["study_start_date"] = None
        completion_date_struct = tdh.safe_get(
            trial_data, ["protocolSection", "statusModule", "completionDateStruct"]
        )
        if completion_date_struct and completion_date_struct.get("type") == "ACTUAL":
            trial_schema["study_completion_date"] = completion_date_struct["date"]
        else:
            trial_schema["study_completion_date"] = None
        officials = tdh.safe_get(
            trial_data, ["protocolSection", "contactsLocationsModule", "overallOfficials"]
        )
        if officials:
            for official in officials:
                if official["role"] == "PRINCIPAL_INVESTIGATOR":
                    trial_schema["principal_investigator"] = official["name"]
                    trial_schema["principal_investigator_institution"] = official["affiliation"]
                    break

        # Populate arms and drug_list
        drug_list = set()
        arm_internal_id = 0
        # A registry record may have interventions but no arm groups
        # (NCT06383338); the KeyError lost the trial in the full run.
        for trial_data_arm in (
            tdh.safe_get(trial_data, ["protocolSection", "armsInterventionsModule", "armGroups"])
            or []
        ):
            arm_description = tdh.safe_get(trial_data_arm, ["description"])
            schema_arm = {
                "arm_code": trial_data_arm["label"],
                "arm_internal_id": arm_internal_id,
                "arm_description": arm_description
                if arm_description
                else tdh.safe_get(trial_data_arm, ["label"]),
                "arm_suspended": "N",
                "dose_level": [],
            }

            trial_schema["treatment_list"]["step"][0]["arm"].append(schema_arm)
            dose_level_code = 0
            for intervention in tdh.safe_get(trial_data_arm, ["interventionNames"]):
                if intervention:
                    drug_list.add(intervention)
                    schema_arm["dose_level"].append(
                        {
                            "level_code": f"{dose_level_code}",
                            "level_description": intervention,
                            "level_internal_id": dose_level_code,
                            "level_suspended": "N",
                        }
                    )
                    dose_level_code = dose_level_code + 1
            arm_internal_id = arm_internal_id + 1
        # Sorted so the CTML does not depend on set order (roadmap 1.9).
        trial_schema["drug_list"]["drug"] = [{"drug_name": drug} for drug in sorted(drug_list)]
    except KeyError as ke:
        logger.error(f"Key {ke} not found in NCT study {nct_id}")
        raise

    # logger.debug(f"CTML: After general mapping | {trial_schema}")
    return trial_schema


# Conversion factors to years for every unit clinicaltrials.gov uses in
# minimumAge. Paediatric trials routinely state ages in months, weeks or days,
# so restricting this to "Years" silently drops the lower age bound.
_AGE_UNIT_IN_YEARS = {
    "year": 1.0,
    "month": 1.0 / 12.0,
    "week": 1.0 / 52.1775,
    "day": 1.0 / 365.25,
    "hour": 1.0 / (365.25 * 24),
    "minute": 1.0 / (365.25 * 24 * 60),
}


def map_age_group(trial_data: dict) -> str:
    """
    Derive the CTML `age` label from the trial's stdAges bands.

    With no stdAges at all the schema default applies, which is "All" - see
    src/ctml_schema.py for why it is not upstream's "Adults". Labels are configurable in src/trial_config.py because the
    vocabulary MatchMiner accepts here is deployment-specific.
    """
    std_ages = tdh.safe_get(trial_data, ["protocolSection", "eligibilityModule", "stdAges"]) or []
    bands = {a.upper() for a in std_ages}
    enrols_children = "CHILD" in bands
    enrols_adults = bool(bands & {"ADULT", "OLDER_ADULT"})

    if enrols_children and enrols_adults:
        return getattr(config, "AGE_LABEL_ALL", "All")
    if enrols_children:
        return getattr(config, "AGE_LABEL_CHILDREN", "Children")
    if enrols_adults:
        return getattr(config, "AGE_LABEL_ADULTS", "Adults")

    logger.warning(f"No stdAges on {get_nct_id(trial_data)}; leaving age as schema default")
    return cs.get_ctml_schema()["age"]


def _parse_age(raw, nct_id=""):
    """(value, unit) from a clinicaltrials.gov age string, or None."""
    if not raw:
        return None
    components = str(raw).split()
    if len(components) < 2:
        logger.warning(f"NCTID: {nct_id} | Could not parse age {raw!r}; omitting the bound")
        return None
    try:
        value = float(components[0])
    except ValueError:
        logger.warning(f"NCTID: {nct_id} | Non-numeric age {raw!r}; omitting the bound")
        return None
    unit = components[1].lower().rstrip("s")  # "Months" -> "month", "Year" -> "year"
    if unit not in _AGE_UNIT_IN_YEARS:
        logger.warning(f"NCTID: {nct_id} | Unknown age unit in {raw!r}; omitting the bound")
        return None
    return value, unit


def _stated_age_years(raw, nct_id=""):
    """The age as stated, in years, with no completed-units offset; or None."""
    parsed = _parse_age(raw, nct_id)
    if parsed is None:
        return None
    value, unit = parsed
    return value * _AGE_UNIT_IN_YEARS[unit]


def _age_bound(raw, operator, nct_id="", unit_offset=0):
    """
    One CTML age_numerical expression from a clinicaltrials.gov age string.

    `unit_offset` is added to the stated value before conversion, in the unit
    the trial stated. It is 1 for an upper bound and 0 for a lower one,
    because the two fields do not mean the same kind of thing.

    minimumAge is exact: "1 Year" admits a patient the day they turn one.
    maximumAge is in completed units - a participant whose "maximum age" is 17
    years is 17 until the day they turn 18 - so the eligible set is age < 18,
    not age <= 17.0. The registry's own trials confirm it: NCT02443831 pairs
    maximumAge "24 Years" with "24 years or younger", NCT06647953 pairs
    "21 Years" with "21 years of age or younger", and NCT03643276 spells it
    out as "age < 18 years (up to 17 years and 365 days)" against a structured
    "17 Years".

    This matters because MatchMiner compares against a birth date: "<=17"
    admits only patients up to 17.0 years and silently drops every eligible
    17-to-18-year-old. In paediatric oncology that is the adolescent and young
    adult group, not a rounding error.

    Returns "" when the value is absent or unparseable - the bound is then
    simply not expressed.
    """
    parsed = _parse_age(raw, nct_id)
    if parsed is None:
        return ""
    value, unit = parsed
    years = round((value + unit_offset) * _AGE_UNIT_IN_YEARS[unit], 2)
    # Keep whole years as integers (">=18"); express the rest to 2dp (">=0.5").
    # MatchMiner reads the fraction as a fraction of a year and converts it to
    # whole months, so 0.5 is six months and 0.08 is one - the same reading
    # this conversion intends.
    if years == int(years):
        return f"{operator}{int(years)}"
    return f"{operator}{years}"


def map_age_numerical(trial_data: dict, prose: dict | None = None) -> list:
    """
    The trial's age bounds as CTML age_numerical expressions, in years.

    Both bounds, in the order lower-then-upper. The upper one is one unit above
    the stated maximum, because maximumAge is in completed units - see
    _age_bound. maximumAge used to be
    discarded, which left every trial open-ended at the top: a study enrolling
    18 to 70 *days* matched every child in the database. 613 of the 924 cached
    trials state a maximum and 56 of those cap below 18, so in a paediatric
    service the missing bound is not a corner case.

    Handles every unit clinicaltrials.gov emits (singular and plural), not just
    "Years". Sub-year ages become decimals - 6 Months -> ">=0.5" - so that
    infant and neonatal trials keep a usable bound at both ends.

    The upper bound is emitted with "<", not "<=", because the value already
    carries the completed-unit offset: maximumAge "40 Years" means age < 41,
    and "<=41" would admit a patient who has turned 41. MatchMiner treats "<"
    and "<=" identically, so this is invisible there - but the flat index
    reads the operator literally (`age_max_inclusive`), and a consumer joining
    on whole years admitted an extra year of patients. Audited 2026-09-29
    (doc/runs/2026-09-29-3.4-audit.md, defect A): 496 of the 765 indexed
    trials with an upper bound were one unit too wide. A maximum the prose
    states as exclusive is likewise "<N", one unit lower.

    `prose` is the model's reading of the age sentence
    (utils.age_bounds.read_age_bounds), or None. It narrows a maximum the
    sponsor meant as exclusive and fills bounds the structured fields leave
    empty; the rules are in utils/age_bounds.py. Without it the result is
    the structured reading alone, exactly as before.
    """
    eligibility = tdh.safe_get(trial_data, ["protocolSection", "eligibilityModule"]) or {}
    nct_id = get_nct_id(trial_data)
    minimum = _age_bound(eligibility.get("minimumAge"), ">=", nct_id)
    maximum = _age_bound(eligibility.get("maximumAge"), "<", nct_id, unit_offset=1)
    if prose is None:
        return [b for b in (minimum, maximum) if b]
    stated_maximum = _stated_age_years(eligibility.get("maximumAge"), nct_id) if maximum else None
    return ab.reconcile_with_structured(minimum, maximum, stated_maximum, prose, nct_id)


def get_nct_keywords(trial_data):
    return tdh.safe_get(trial_data, ["protocolSection", "conditionsModule", "keywords"])


def get_nct_id(trial_data):
    return trial_data["protocolSection"]["identificationModule"]["nctId"]


def get_full_nct_eligibility_criteria(trial_data):
    return tdh.safe_get(trial_data, ["protocolSection", "eligibilityModule", "eligibilityCriteria"])


def map_gender(trial_data: dict):
    nct_gender = tdh.safe_get(trial_data, ["protocolSection", "eligibilityModule", "sex"])
    gender_mapping = {"male": "Male", "female": "Female"}
    return gender_mapping.get(nct_gender.lower(), "")


def _map_global_diagnosis_from_conditions_and_extra_info(trial_data: dict) -> set:
    nct_id = get_nct_id(trial_data)
    conditions_list = tdh.safe_get(
        trial_data, ["protocolSection", "conditionsModule", "conditions"]
    )
    all_possible_diagnoses = set()

    wildcards = diagnosis._basket_wildcards(conditions_list, nct_id)
    if wildcards:
        all_possible_diagnoses.update(wildcards)
    else:
        level_1_diagnosis, l1_to_all_mapping = onct.get_all_oncotree_data()
        logger.debug(f"NCTID: {nct_id} | Stage 1 - Original Conditions:{conditions_list}")
        level1_oncotree_values_dict = dx_prompts.get_level1_diagnosis_from_original_conditions(
            nct_id, conditions_list, level_1_diagnosis
        )
        logger.debug(
            f"NCTID: {nct_id} | Stage 2 - Mapped original conditions to Level 1:{level1_oncotree_values_dict}"
        )

        for item in level1_oncotree_values_dict["oncotree_diagnoses"]:
            if item["oncotree_value"] == "" or item["oncotree_value"].lower() == "other":
                logger.debug(
                    f"NCTID: {nct_id} | Skipping condition {item['cancer_condition']} as no oncotree diagnosis was returned"
                )
                continue
            child_oncotree_values = l1_to_all_mapping[item["oncotree_value"]]
            nct_condition = item["cancer_condition"]
            logger.debug(
                f"NCTID: {nct_id} | Stage 3 - Condition = {nct_condition}. Child values = {child_oncotree_values}"
            )
            if len(child_oncotree_values) > 0:
                oncotree_diagnoses_result = dx_prompts.get_child_level_diagnoses_from_condition(
                    nct_id, child_oncotree_values, nct_condition
                )
                if (
                    oncotree_diagnoses_result
                    and "oncotree_diagnoses" in oncotree_diagnoses_result.keys()
                ):
                    all_possible_diagnoses.update(oncotree_diagnoses_result["oncotree_diagnoses"])

        if len(all_possible_diagnoses) == 0:
            logger.info(
                f"NCTID: {nct_id} | No oncotree diagnosis was found from original conditions, trying from keywords and title"
            )
            extra_info = []
            keywords = get_nct_keywords(trial_data)
            if keywords:
                extra_info.extend(keywords)
            long_title = tdh.safe_get(
                trial_data, ["protocolSection", "identificationModule", "officialTitle"]
            )
            brief_title = tdh.safe_get(
                trial_data, ["protocolSection", "identificationModule", "briefTitle"]
            )
            extra_info.append(long_title)
            extra_info.append(brief_title)

            all_level_oncotree_values = set()
            level1_oncotree_values_dict = dx_prompts.get_oncotree_diagnoses_from_trial_info(
                nct_id, extra_info, level_1_diagnosis
            )
            level1_diagnoses = level1_oncotree_values_dict.get("oncotree_diagnoses", [])
            if not level1_diagnoses:
                logger.debug(
                    f"NCTID: {nct_id} | No level 1 diagnoses from keywords/title, skipping child-level mapping"
                )
            else:
                for item in level1_diagnoses:
                    if item == "" or item.lower() == "other":
                        continue
                    child_oncotree_values = l1_to_all_mapping[item]
                    all_level_oncotree_values.update(child_oncotree_values)
                logger.debug(
                    f"NCTID: {nct_id} | Stage 3 - Diagnoses = {level1_diagnoses}. Child values = {all_level_oncotree_values}"
                )
                if all_level_oncotree_values:
                    oncotree_diagnoses_result = dx_prompts.get_oncotree_diagnoses_from_trial_info(
                        nct_id, extra_info, all_level_oncotree_values
                    )
                    if (
                        oncotree_diagnoses_result
                        and "oncotree_diagnoses" in oncotree_diagnoses_result.keys()
                    ):
                        all_possible_diagnoses.update(
                            oncotree_diagnoses_result["oncotree_diagnoses"]
                        )

    return all_possible_diagnoses


def map_global_diagnosis_to_oncotree_term(
    trial_data: dict, global_eligibility_criteria: str = ""
) -> list:
    nct_id = get_nct_id(trial_data)
    all_possible_diagnoses = set()

    # Read the trial's own condition list first. It costs no tokens, cannot
    # hallucinate, and on the curated benchmark a plain lookup of these strings
    # against Oncotree scores within 0.02 of what the 70B model achieves
    # through both LLM stages. It is a floor, not a replacement: precision is
    # high but it finds only about a third of the answers.
    conditions_list = (
        tdh.safe_get(trial_data, ["protocolSection", "conditionsModule", "conditions"]) or []
    )
    seeded, from_eligibility = diagnosis.seed_and_map_diagnosis(
        nct_id, conditions_list, global_eligibility_criteria
    )
    all_possible_diagnoses.update(seeded)
    all_possible_diagnoses.update(from_eligibility)

    if not from_eligibility:
        logger.info(
            f"NCTID: {nct_id} | No oncotree diagnosis from eligibility criteria, falling back to conditions and extra info"
        )
        all_possible_diagnoses.update(
            _map_global_diagnosis_from_conditions_and_extra_info(trial_data)
        )

    logger.debug(f"NCTID: {nct_id} | Stage 4 Oncotree_diagnoses : {all_possible_diagnoses}")

    if len(all_possible_diagnoses) == 0:
        # Deliberately not an exception. Raising loses the whole trial - its
        # genomic criteria, its age bounds, everything - and a trial absent
        # from MatchMiner is a trial no patient can be matched to, which is
        # the one failure a reviewer cannot see. The asymmetry decides it: an
        # over-broad trial costs a clinician minutes, a missing one can cost a
        # patient a trial they were eligible for. The trial is produced without
        # a diagnosis criterion and routed to the review queue instead.
        logger.error(
            f"NCTID: {nct_id} | NEEDS REVIEW: no Oncotree diagnosis could be "
            f"determined from the eligibility criteria, the conditions, the "
            f"keywords or the title. Mapping continues without a diagnosis "
            f"criterion; a human must supply one."
        )
    return sorted(all_possible_diagnoses)


def map_prior_treatment_requirements(trial_schema, trial_data) -> dict:
    """
    Special logic to map the inclusion and exclusion criteria, along with prefixing the exclusion criteria with 'Exclude -'
    Updates the incoming trial_schema to add 'prior_treatment_requirements' key

    Parameters
    ----------
    trial_schema: dict
        Dictionary containing the keys and values for a trial as per the clinical trial schema for matchminer
    trial_data: dict
        Dictionary containing the response from https://clinicaltrials.gov/ API for a particular trial
    """
    eligibility_criteria = get_full_nct_eligibility_criteria(trial_data)

    lines = eligibility_criteria.split("\n")
    begin_exclude = False
    # Populate prior_treatment_requirements
    for line in lines:
        if "Exclusion Criteria" in line:
            begin_exclude = True
        stripped_line = line.strip()
        if stripped_line:
            # Prefix exclusion criteria lines with "exclude"
            if begin_exclude:
                trial_schema["prior_treatment_requirements"].append(f"Exclude - {stripped_line}")
            else:
                # Add inclusion criteria lines directly
                trial_schema["prior_treatment_requirements"].append(stripped_line)
    return trial_schema


def split_inclusion_exclusion_criteria(trial_data: dict) -> tuple[str, str]:
    """
    Splits the eligibility criteria into inclusion and exclusion parts
    """
    eligibility_criteria = get_full_nct_eligibility_criteria(trial_data)
    index = exclusion_heading(eligibility_criteria)
    if index is not None:
        return eligibility_criteria[:index], eligibility_criteria[
            index + len("exclusion criteria") :
        ]
    inclusion_criteria, exclusion_criteria = tdh.split_with_find(
        eligibility_criteria, ["exclusion criteria", "exclusion"]
    )
    return inclusion_criteria, exclusion_criteria


# "exclusion criteria" in running text rather than as the heading: "meet the
# following inclusion and exclusion criteria" (NCT05278208), "drug-specific
# inclusion/exclusion criteria", "any of the exclusion criteria below". Until
# 2026-09-27 the split cut at the first occurrence, so in 18 in-scope trials
# the real inclusion text was read, and labelled for the model, as exclusions.
_NOT_A_HEADING = re.compile(
    r"(?:inclusion\s*(?:and|or|/|&)\s*|enrol(?:l)?ment\s*/\s*|(?:the|any|all|other|these|those|following|"
    r"specific|of)\s+|-\s*specific\s+)$",
    re.I,
)


def exclusion_heading(text: str):
    """
    Index of the "Exclusion Criteria" heading, or None if there is none.
    The first occurrence not preceded by words that make it a phrase in
    running text (see _NOT_A_HEADING) is the heading.
    """
    for m in re.finditer(r"exclusion criteria", text, re.I):
        before = text[max(0, m.start() - 40) : m.start()]
        if not _NOT_A_HEADING.search(before):
            return m.start()
    return None
