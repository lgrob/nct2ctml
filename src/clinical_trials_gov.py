# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

"""
This script contains methods that deal with extraction and manipulation
of data from clinicaltrials.gov
"""
import sys
import os
import csv
import json
from typing import Dict, List

sys.path.append(os.path.abspath("../"))

import src.trial_config as config
import requests
import urllib.parse
import src.ctml_schema as cs
import utils.ai_helper as ai
import src.trial_data_helper as tdh
import utils.oncotree as onct
import utils.reference_validation as rv
import src.trial_criteria_to_genes as ctg
import src.match_criteria_mapper as mcm
from src.match_criteria_mapper import ArmCriteriaBlocks, ArmCriteriaText
from loguru import logger


def map_nct_to_ctml(trial_data: dict, gene_synonym_mapping: Dict[str, List[str]]) -> dict:
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

    updated_trial_schema = map_nct_to_clinical_and_genomic_criteria(trial_data, 
                                                                    all_arms_criteria, 
                                                                    trial_schema,
                                                                    gene_synonym_mapping)

    logger.debug(f"CTML: After mapping clinical and genomic match criteria | {updated_trial_schema}")

    return updated_trial_schema

def map_nct_to_clinical_and_genomic_criteria(trial_data: dict, 
                                             all_arms_criteria: ArmCriteriaBlocks, 
                                             trial_schema: dict,
                                             gene_synonym_mapping: Dict[str, List[str]]) -> dict:
    nct_id = get_nct_id(trial_data)
    
    global_nct_criteria = ArmCriteriaText.get_combined_eligibility_text(all_arms_criteria.get("global", {}))
    global_inclusion_text = all_arms_criteria.get("global", {}).get("inclusion_text", "")
    global_exclusion_text = all_arms_criteria.get("global", {}).get("exclusion_text", "")

    keywords = get_nct_keywords(trial_data)

    # map global clinical criteria

    mapped_global_clinical_critera = {}

    logger.info(f"NCTID: {nct_id} | Mapping global diagnosis to oncotree terms")
    oncotree_diagnoses_list = map_global_diagnosis_to_oncotree_term(trial_data, global_nct_criteria)
    mapped_global_clinical_critera['oncotree_primary_diagnosis'] = oncotree_diagnoses_list

    # A list, because a trial can bound age at both ends. The converter emits
    # each bound as its own clinical node - two age_numerical keys cannot live
    # in one dict, and MatchMiner intersects sibling nodes anyway.
    age_bounds = map_age_numerical(trial_data)
    if age_bounds:
        mapped_global_clinical_critera['age_numerical'] = age_bounds
    
    gender_str = map_gender(trial_data)
    if gender_str:
        mapped_global_clinical_critera['gender'] = gender_str
    
    logger.info(f"NCTID: {nct_id} | Mapping disease status")
    disease_status_dict = map_disease_status(nct_id, global_nct_criteria, keywords)
    if disease_status_dict and len(disease_status_dict.get('disease_status', {})) > 0:
        mapped_global_clinical_critera.update(disease_status_dict)

    biomarker_status_dict = _map_biomarker_statuses(nct_id, global_nct_criteria, keywords,level="global")
    mapped_global_clinical_critera.update(biomarker_status_dict)

    logger.debug(f"global clinical criteria: {mapped_global_clinical_critera}")
    global_clinical_ctml = mcm.convert_to_ctml_clinical_schema(mapped_global_clinical_critera, nct_id)

    # map global genomic criteria

    logger.info(f"NCTID: {nct_id} | Mapping global genomic criteria")
    global_genomic_ctml = map_ctml_match_genomic_criteria(nct_id, gene_synonym_mapping, global_inclusion_text, global_exclusion_text)
    trial_level_match_result = mcm.combine_clinical_and_genomic_ctml(global_clinical_ctml, global_genomic_ctml)
    match_list = trial_schema['treatment_list']['step'][0]['match']
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


def _map_biomarker_statuses(
    nct_id: str,
    eligibility_criteria: str,
    keywords: list,
    level: str,
) -> dict:
    logger.info(f"NCTID: {nct_id} | Mapping {level} HER2/ER/PR status")
    status_dict = map_her2_er_pr_status(nct_id, eligibility_criteria, keywords)

    logger.info(f"NCTID: {nct_id} | Mapping {level} PDL1 status")
    status_dict.update(map_pdl1_status(nct_id, eligibility_criteria, keywords))

    logger.info(f"NCTID: {nct_id} | Mapping {level} MMR/MS status")
    status_dict.update(map_mmr_ms_status(nct_id, eligibility_criteria, keywords))

    return status_dict


def _map_arm_level_matches(
    nct_id: str,
    all_arms_criteria: ArmCriteriaBlocks,
    trial_schema: dict,
    keywords: list,
    gene_synonym_mapping: Dict[str, List[str]],
) -> None:
    # Handle conversion at arm level if there are arm specific criteria.
    for level_code, arm_criteria in all_arms_criteria.items():
        if level_code == "global":
            continue
        if arm_criteria["inclusion_text"] == "" and arm_criteria["exclusion_text"] == "":
            continue

        arm_eligibility_criteria = ArmCriteriaText.get_combined_eligibility_text(arm_criteria)
        arm_inclusion_text = arm_criteria.get("inclusion_text", "")
        arm_exclusion_text = arm_criteria.get("exclusion_text", "")
        mapped_arm_clinical_critera = {}

        logger.info(
            f"NCTID: {nct_id} | Mapping arm level diagnosis to oncotree terms for arm {level_code}"
        )
        oncotree_diagnoses_list = map_eligibility_criteria_to_oncotree_term(
            nct_id, arm_eligibility_criteria
        )
        if oncotree_diagnoses_list and len(oncotree_diagnoses_list) > 0:
            mapped_arm_clinical_critera["oncotree_primary_diagnosis"] = oncotree_diagnoses_list
        mapped_arm_clinical_critera.update(
            _map_biomarker_statuses(
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
        arm_genomic_ctml = map_ctml_match_genomic_criteria(
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
    arm_groups = trial_data["protocolSection"]["armsInterventionsModule"]["armGroups"]
    inclusion_text, exclusion_text = split_inclusion_exclusion_criteria(trial_data)

    arm_mapping = ai.get_arm_criteria_mapping(
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
    label_to_text: Dict[str, Dict[str, str]] = {}
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
    ctml_arms = (
        trial_schema.get("treatment_list", {})
        .get("step", [{}])[0]
        .get("arm", [])
    )

    for ctml_arm in ctml_arms:
        if not isinstance(ctml_arm, dict):
            continue

        ctml_arm_code = ctml_arm.get("arm_code")
        if not isinstance(ctml_arm_code, str) or not ctml_arm_code:
            # If arm_code is missing or malformed, skip attaching per-arm text.
            continue

        per_arm_text = label_to_text.get(ctml_arm_code, {"inclusion_text": "", "exclusion_text": ""})

        arm_criteria_blocks[ctml_arm_code] = {
            "inclusion_text": per_arm_text.get("inclusion_text", ""),
            "exclusion_text": per_arm_text.get("exclusion_text", ""),
        }

    return arm_criteria_blocks

def map_ctml_general_fields(trial_schema, trial_data) -> dict:

    nct_id = trial_data['protocolSection']['identificationModule']['nctId']

    try:    
        trial_schema['nct_id'] = nct_id
        trial_schema['age'] = map_age_group(trial_data)
        trial_schema['long_title'] = trial_data['protocolSection']['identificationModule']['officialTitle']
        trial_schema['principal_investigator_institution'] = trial_data['protocolSection']['identificationModule']['organization']['fullName']
        trial_schema['principal_investigator'] = 'NA' # overwrriten later if a PI is found in overall officials list

        phases = trial_data['protocolSection']['designModule']['phases']
        trial_schema['phase'] = phases[0] if len(phases) > 0 else ''
        trial_schema['short_title'] = trial_data['protocolSection']['identificationModule']['briefTitle']
        trial_schema['summary'] = trial_data['protocolSection']['descriptionModule']['briefSummary']
        trial_schema['protocol_target_accrual'] = trial_data['protocolSection']['designModule']['enrollmentInfo']['count']
        trial_schema['sponsor_list']['sponsor'].append(
            {
                'is_principal_sponsor': 'Y',
                'sponsor_name':trial_data['protocolSection']['sponsorCollaboratorsModule']['leadSponsor']['name'],
                'sponsor_protocol_no':'',
                'sponsor_roles': 'sponsor'
            }
        )

        trial_schema['curated_on'] = trial_data['protocolSection']['statusModule']['studyFirstPostDateStruct']['date']
        trial_schema['last_updated'] = trial_data['protocolSection']['statusModule']['lastUpdatePostDateStruct']['date']

        start_date_struct = tdh.safe_get(trial_data, ['protocolSection','statusModule','startDateStruct'])
        if start_date_struct and start_date_struct.get('type') == 'ACTUAL':
            trial_schema['study_start_date'] = start_date_struct['date']
        else: 
            trial_schema['study_start_date'] = None
        completion_date_struct = tdh.safe_get(trial_data, ['protocolSection','statusModule','completionDateStruct'])
        if completion_date_struct and completion_date_struct.get('type') == 'ACTUAL':
            trial_schema['study_completion_date'] = completion_date_struct['date']
        else:
            trial_schema['study_completion_date'] = None
        officials = tdh.safe_get(trial_data, ['protocolSection','contactsLocationsModule','overallOfficials'])
        if officials:
            for official in officials:
                if official['role'] == 'PRINCIPAL_INVESTIGATOR':
                    trial_schema['principal_investigator'] = official['name']
                    trial_schema['principal_investigator_institution'] = official['affiliation']
                    break

        # Populate arms and drug_list
        drug_list = set()
        arm_internal_id = 0
        for trial_data_arm in trial_data['protocolSection']['armsInterventionsModule']['armGroups']:
            arm_description = tdh.safe_get(trial_data_arm, ['description'])
            schema_arm = {
                    'arm_code': trial_data_arm['label'],
                    'arm_internal_id': arm_internal_id,
                    'arm_description': arm_description if arm_description else tdh.safe_get(trial_data_arm, ['label']),
                    'arm_suspended': 'N',
                    'dose_level': []            
                }

            trial_schema['treatment_list']['step'][0]['arm'].append(schema_arm)
            dose_level_code = 0
            for intervention in tdh.safe_get(trial_data_arm, ['interventionNames']):
                if intervention:
                    drug_list.add(intervention) 
                    schema_arm['dose_level'].append({
                        'level_code': f'{dose_level_code}',
                        'level_description': intervention,
                        'level_internal_id': dose_level_code,
                        'level_suspended': 'N'
                    })
                    dose_level_code = dose_level_code + 1
            arm_internal_id = arm_internal_id + 1
        trial_schema['drug_list']['drug'] =[{'drug_name': drug} for drug in drug_list]
    except KeyError as ke:
        logger.error(f"Key {ke} not found in NCT study {nct_id}")
        raise
        
    #logger.debug(f"CTML: After general mapping | {trial_schema}")
    return trial_schema

def map_ctml_match_genomic_criteria(trial_id: str, gene_synonym_mapping:Dict[str, List[str]], inclusion_text: str, exclusion_text: str):
    """
    Map genomic criteria out of free-text eligibility.

    Source-agnostic: takes the trial's identifier rather than a
    ClinicalTrials.gov document, so CTIS records reach the same gene
    extraction, contradiction resolution and enrichment path.
    """
    nct_id = trial_id
    eligibilityCriteria = inclusion_text + "\n" + exclusion_text
    contains_gene_info = mcm.check_if_eligibility_criteria_contains_gene_info(gene_synonym_mapping, eligibilityCriteria) #check if eligibility criteria contains any gene before asking AI

    if contains_gene_info: 
        tcg = ctg.TrialCriteriaToGenes(
            trial_criteria=eligibilityCriteria,
            synonym_to_symbol=gene_synonym_mapping,
        )
        gene_symbols = tcg.extract_official_gene_symbols()

        inlcusion_genomic_criteria = []
        exclusion_genomic_criteria = []

        # Pass 1: Initial extraction of genomic criteria
        if inclusion_text:
            inlcusion_genomic_criteria = ai.get_inclusion_genomic_criteria(nct_id, gene_symbols, inclusion_text)
            print(f'inlcusion_genomic_criteria: {inlcusion_genomic_criteria}')
            inlcusion_genomic_criteria = _normalize_genomic_criteria(inlcusion_genomic_criteria)
            # Pass 2: Enrichment for detailed mutation/CNV information
            inlcusion_genomic_criteria = _enrich_genomic_criteria(
                nct_id, inlcusion_genomic_criteria, inclusion_text
            )            
            print(f'inclusion_genomic_criteria after enrichment: {inlcusion_genomic_criteria}')

        if exclusion_text:
            exclusion_genomic_criteria = ai.get_exclusion_genomic_criteria(nct_id, gene_symbols, exclusion_text)            
            print(f'exclusion_genomic_criteria: {exclusion_genomic_criteria}')
            exclusion_genomic_criteria = _normalize_genomic_criteria(exclusion_genomic_criteria)
            exclusion_genomic_criteria = _enrich_genomic_criteria(
                nct_id, exclusion_genomic_criteria, exclusion_text
            )
            print(f'exclusion_genomic_criteria after enrichment: {exclusion_genomic_criteria}')

        genomic_ctml = mcm.convert_to_ctml_genomic_schema(
            inlcusion_genomic_criteria, exclusion_genomic_criteria,
            inclusion_text, exclusion_text, nct_id)
        logger.debug(f"genomic criteria as CTML: {genomic_ctml}")
        return genomic_ctml
    else:
        return {}

def _normalize_genomic_criteria(genomic_criteria):
    """
    Normalize possible model output shapes into:
      [{'genomic': {...}}, ...]

    Supported inputs include:
      - {'genomic': {...}}
      - {'genomic': [{...}, {...}]}
      - [{'genomic': {...}}, ...]
      - [{'hugo_symbol': 'EGFR', 'variant_category': 'Mutation'}, ...]
    """
    if not genomic_criteria:
        return genomic_criteria

    if isinstance(genomic_criteria, dict):
        if isinstance(genomic_criteria.get("genomic"), list):
            genomic_criteria = [{"genomic": g} for g in genomic_criteria["genomic"] if isinstance(g, dict)]
        else:
            genomic_criteria = [genomic_criteria]

    normalized_criteria = []
    for criterion in genomic_criteria:
        # Handle list items that are already gene-level dicts
        if isinstance(criterion, dict) and "genomic" not in criterion and (
            "hugo_symbol" in criterion or "variant_category" in criterion
        ):
            normalized_criteria.append({"genomic": criterion})
            continue

        if isinstance(criterion, dict) and isinstance(criterion.get("genomic"), list):
            for g in criterion["genomic"]:
                if isinstance(g, dict):
                    normalized_criteria.append({"genomic": g})
            continue

        normalized_criteria.append(criterion)

    return normalized_criteria

def _enrich_genomic_criteria(nct_id: str, genomic_criteria: list, criteria_text: str) -> list:
    """
    Perform second-pass enrichment on genomic criteria to extract additional details.
    
    This function checks if the criteria text contains keywords suggesting mutation
    or CNV details, and if matching criteria exist, calls the appropriate enrichment
    functions to add variant_classification, exon, or cnv_call fields.
    
    Args:
        nct_id: The clinical trial identifier for logging.
        genomic_criteria: List of genomic criteria from initial extraction.
        Example: [{'genomic': {'hugo_symbol': 'EGFR', 'variant_category': 'Mutation', 'protein_change': 'p.E19del'}}, {'genomic': {'hugo_symbol': 'EGFR', 'variant_category': 'Mutation', 'protein_change': 'p.L858R'}}]
        criteria_text: The eligibility criteria text to analyze.
        
    Returns:
        The genomic_criteria list with enriched fields merged in.
    """
    if not genomic_criteria or not criteria_text:
        return genomic_criteria

    # Caller should normalize output; warn if not in canonical shape.
    # Expected: [{'genomic': {...}}, ...]
    is_canonical = isinstance(genomic_criteria, list) and all(
        isinstance(c, dict) and isinstance(c.get("genomic"), dict) for c in genomic_criteria
    )
    if not is_canonical:
        try:
            sample = repr(genomic_criteria)
        except Exception:
            sample = "<unrepr-able>"
        sample = sample[:500] + ("..." if len(sample) > 500 else "")
        logger.warning(
            f"NCTID: {nct_id} | Unexpected genomic_criteria shape passed to _enrich_genomic_criteria; "
            f"expected list of {{'genomic': dict}}. Got type={type(genomic_criteria).__name__}. Sample={sample}"
        )
    
    # Separate criteria by variant_category
    mutation_criteria = []
    cnv_criteria = []

    for criterion in genomic_criteria:
        if not isinstance(criterion, dict):
            continue
        genomic = criterion.get("genomic", {})
        if isinstance(genomic, dict) and genomic:
            variant_category = genomic.get("variant_category", "")
            
            # Handle both positive and negated categories
            category_base = variant_category.lstrip("!")
            
            if category_base == "Mutation":
                mutation_criteria.append(criterion)
            elif category_base == "Copy Number Variation":
                cnv_criteria.append(criterion)
    
    # Enrich mutations if criteria text contains mutation detail keywords
    if mutation_criteria and ai.has_mutation_details(criteria_text):
        logger.info(f"NCTID: {nct_id} | Detected mutation details in criteria, enriching {len(mutation_criteria)} mutation(s)")
        enriched_mutations = ai.enrich_mutation_details(nct_id, mutation_criteria, criteria_text)
        if enriched_mutations:
            # Merge into the mutation_criteria list; these are references into genomic_criteria
            ai.merge_enriched_criteria(mutation_criteria, enriched_mutations, enrichment_type="mutation")
    
    # Enrich CNVs if criteria text contains CNV detail keywords
    if cnv_criteria and ai.has_cnv_details(criteria_text):
        logger.info(f"NCTID: {nct_id} | Detected CNV details in criteria, enriching {len(cnv_criteria)} CNV(s)")
        enriched_cnvs = ai.enrich_cnv_details(nct_id, cnv_criteria, criteria_text)
        if enriched_cnvs:
            # Merge into the cnv_criteria list; these are references into genomic_criteria
            ai.merge_enriched_criteria(cnv_criteria, enriched_cnvs, enrichment_type="cnv")
    
    return genomic_criteria

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

    The schema default is "Adults", which is wrong for any trial enrolling
    children. Labels are configurable in src/trial_config.py because the
    vocabulary MatchMiner accepts here is deployment-specific.
    """
    std_ages = tdh.safe_get(trial_data, ['protocolSection', 'eligibilityModule', 'stdAges']) or []
    bands = {a.upper() for a in std_ages}
    enrols_children = 'CHILD' in bands
    enrols_adults = bool(bands & {'ADULT', 'OLDER_ADULT'})

    if enrols_children and enrols_adults:
        return getattr(config, 'AGE_LABEL_ALL', 'All')
    if enrols_children:
        return getattr(config, 'AGE_LABEL_CHILDREN', 'Children')
    if enrols_adults:
        return getattr(config, 'AGE_LABEL_ADULTS', 'Adults')

    logger.warning(f"No stdAges on {get_nct_id(trial_data)}; leaving age as schema default")
    return cs.get_ctml_schema()['age']


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
    if not raw:
        return ""

    components = str(raw).split()
    if len(components) < 2:
        logger.warning(f"NCTID: {nct_id} | Could not parse age {raw!r}; omitting the bound")
        return ""

    try:
        value = float(components[0])
    except ValueError:
        logger.warning(f"NCTID: {nct_id} | Non-numeric age {raw!r}; omitting the bound")
        return ""

    unit = components[1].lower().rstrip('s')  # "Months" -> "month", "Year" -> "year"
    if unit not in _AGE_UNIT_IN_YEARS:
        logger.warning(f"NCTID: {nct_id} | Unknown age unit in {raw!r}; omitting the bound")
        return ""

    years = round((value + unit_offset) * _AGE_UNIT_IN_YEARS[unit], 2)
    # Keep whole years as integers (">=18"); express the rest to 2dp (">=0.5").
    # MatchMiner reads the fraction as a fraction of a year and converts it to
    # whole months, so 0.5 is six months and 0.08 is one - the same reading
    # this conversion intends.
    if years == int(years):
        return f"{operator}{int(years)}"
    return f"{operator}{years}"


def map_age_numerical(trial_data: dict) -> list:
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

    Note that MatchMiner treats "<" and "<=" identically (likewise ">" and
    ">="), so the inclusive forms are used throughout; nothing is lost.
    """
    eligibility = tdh.safe_get(trial_data, ['protocolSection', 'eligibilityModule']) or {}
    nct_id = get_nct_id(trial_data)
    bounds = [_age_bound(eligibility.get('minimumAge'), ">=", nct_id),
              _age_bound(eligibility.get('maximumAge'), "<=", nct_id, unit_offset=1)]
    return [b for b in bounds if b]


def map_her2_er_pr_status(nct_id: str, eligibilityCriteria: str, keywords:list):    
    result = ai.get_her2_er_pr_status(nct_id, eligibilityCriteria, keywords)
    filtered_her2_er_pr_dict = {k:v for k,v in result.items() if v.lower() in ["positive", "negative","!positive","!negative"]}
    return filtered_her2_er_pr_dict

def get_nct_keywords(trial_data):
    return tdh.safe_get(trial_data, ['protocolSection','conditionsModule','keywords'])

def get_nct_id(trial_data):
    return trial_data['protocolSection']['identificationModule']['nctId']

def get_full_nct_eligibility_criteria(trial_data):
    return tdh.safe_get(trial_data, ['protocolSection','eligibilityModule','eligibilityCriteria'])

def map_pdl1_status(nct_id: str, eligibilityCriteria: str, keywords:list):
    contains_pdl1_info = mcm.check_if_eligibility_criteria_contains_pdl1_info(keywords, eligibilityCriteria)
    if contains_pdl1_info:
        result = ai.get_pdl1_status(nct_id, eligibilityCriteria, keywords)        
        filtered_pdl1_status_dict = {k:v for k,v in result.items() if v.lower() in ["high", "low"]}
        return filtered_pdl1_status_dict
    return {}

def map_mmr_ms_status(nct_id: str, eligibilityCriteria: str, keywords:list):
    filtered_mmr_ms_status_dict = {}
    contains_mmr_info = mcm.check_if_eligibility_criteria_contains_mmr_info(keywords, eligibilityCriteria)
    if contains_mmr_info:
        mmr_ms_status_dict = ai.get_mmr_status(nct_id, eligibilityCriteria, keywords)
        if 'mmr_status' in mmr_ms_status_dict:
            mmr_value = mmr_ms_status_dict['mmr_status']
            if mmr_value in ['MMR-Proficient', 'MMR-Deficient','!MMR-Proficient', '!MMR-Deficient']:
                filtered_mmr_ms_status_dict['mmr_status'] = mmr_value
            
        if 'ms_status' in mmr_ms_status_dict:
            ms_value = mmr_ms_status_dict['ms_status']
            if ms_value in ['MSI-H', 'MSI-L', 'MSS', '!MSI-H', '!MSI-L']:
                filtered_mmr_ms_status_dict['ms_status'] = ms_value
    return filtered_mmr_ms_status_dict

def map_gender(trial_data: dict):
    nct_gender = tdh.safe_get(trial_data, ['protocolSection', 'eligibilityModule', 'sex'])
    gender_mapping = {
        "male": "Male",
        "female": "Female"}
    result = gender_mapping.get(nct_gender.lower(), {})
    return result

def map_disease_status(nct_id: str, eligibilityCriteria: str, keywords: list):
    result = ai.get_disease_status(nct_id, eligibilityCriteria, keywords)
    return result

def map_eligibility_criteria_to_oncotree_term(nct_id: str, eligibility_criteria: str,
                                              seed_terms=()) -> list:
    """
    Two-stage mapping: pick level_1 nodes, then pick children within them.

    `seed_terms` are Oncotree terms already known to apply - typically read
    straight out of the trial's own conditions - and their branches are added
    to the second stage no matter what the first stage chose. Without that
    floor a wrong level_1 makes the right answer unreachable rather than
    merely unlikely: neuroblastoma sits under Peripheral Nervous System, but
    it arises in the adrenal medulla, so "Adrenal Gland" is the natural pick
    and its only children are Adrenocortical Adenoma, Adrenocortical Carcinoma
    and Pheochromocytoma. Five of six neuroblastoma trials in the benchmark
    returned exactly that pair, with no error raised.
    """
    level_1_diagnosis, l1_to_all_mapping = onct.get_all_oncotree_data()
    level1_oncotree_values_dict = ai.get_oncotree_diagnoses_from_trial_info(nct_id, eligibility_criteria, level_1_diagnosis)
    level1_diagnoses = level1_oncotree_values_dict.get("oncotree_diagnoses", [])

    all_level_oncotree_values = set()
    all_possible_diagnoses = set()
    for item in level1_diagnoses:
        if item == "" or item.lower() == "other":
            continue
        child_oncotree_values = l1_to_all_mapping[item]
        all_level_oncotree_values.update(child_oncotree_values)

    seed_terms = {t for t in (seed_terms or ()) if t}
    forced = {parent for parent, children in l1_to_all_mapping.items()
              if seed_terms & children}
    for parent in forced:
        all_level_oncotree_values.update(l1_to_all_mapping[parent])
    if forced:
        logger.info(f"NCTID: {nct_id} | Forcing {sorted(forced)} into the child-level "
                    f"list; the trial names {sorted(seed_terms)} outright")

    logger.debug(f"NCTID: {nct_id} | Diagnoses = {level1_diagnoses}. Child values = {all_level_oncotree_values}")
    if not all_level_oncotree_values:
        logger.debug(f"NCTID: {nct_id} | No child oncotree values to map, skipping child-level diagnosis request")
        return []

    oncotree_diagnoses_result = ai.get_oncotree_diagnoses_from_trial_info(nct_id, eligibility_criteria, all_level_oncotree_values)
    if oncotree_diagnoses_result and 'oncotree_diagnoses' in oncotree_diagnoses_result.keys():
        all_possible_diagnoses.update(oncotree_diagnoses_result['oncotree_diagnoses'])   
    return list(all_possible_diagnoses)

def _basket_wildcards(conditions_list, nct_id: str = "") -> set:
    """
    The MatchMiner wildcards this trial's conditions justify, if any.

    A broad condition alone is not enough. Registries routinely file a
    category header beside the actual diagnoses: NCT04775485 lists
    "Advanced Solid Tumor" next to "Low-grade Glioma", and NCT04897321 puts
    "Pediatric Solid Tumor" ahead of osteosarcoma, rhabdomyosarcoma,
    neuroblastoma, Ewing sarcoma and Wilms tumour. Reading those as baskets
    throws away a precise answer and replaces it with _SOLID_, which matches
    every solid-tumour patient in the database - the failure a clinician
    notices as noise and a curator never sees.

    31 of the 104 cached trials whose conditions contain a broad term also
    name a specific Oncotree diagnosis, so this is not a corner case.

    The broad term therefore wins only when the trial names nothing specific.
    NCT02813135 is the shape that qualifies: its sole condition is "Pediatric
    Cancer" and its criterion is "a haematologic or solid tumor malignancy
    that has progressed despite standard therapy".
    """
    broad_any = tdh.all_tumours(conditions_list)
    broad_solid = tdh.all_solid_tumours(conditions_list)
    if not (broad_any or broad_solid):
        return set()

    named = rv.diagnoses_from_conditions(conditions_list)
    if named:
        logger.info(
            f"NCTID: {nct_id} | Conditions contain a broad term but also name "
            f"{sorted(named)}. Treating the broad term as a category header, "
            f"not a basket, and mapping the specific diagnoses instead."
        )
        return set()

    return {"_SOLID_", "_LIQUID_"} if broad_any else {"_SOLID_"}


def _map_global_diagnosis_from_conditions_and_extra_info(trial_data: dict) -> set:
    nct_id = get_nct_id(trial_data)
    conditions_list = tdh.safe_get(trial_data, ['protocolSection', 'conditionsModule', 'conditions'])
    all_possible_diagnoses = set()

    wildcards = _basket_wildcards(conditions_list, nct_id)
    if wildcards:
        all_possible_diagnoses.update(wildcards)
    else:
        level_1_diagnosis, l1_to_all_mapping = onct.get_all_oncotree_data()
        logger.debug(f"NCTID: {nct_id} | Stage 1 - Original Conditions:{conditions_list}")
        level1_oncotree_values_dict = ai.get_level1_diagnosis_from_original_conditions(nct_id, conditions_list, level_1_diagnosis)
        logger.debug(f"NCTID: {nct_id} | Stage 2 - Mapped original conditions to Level 1:{level1_oncotree_values_dict}")

        for item in level1_oncotree_values_dict["oncotree_diagnoses"]:
            if item['oncotree_value'] == "" or item['oncotree_value'].lower() == "other":
                logger.debug(f"NCTID: {nct_id} | Skipping condition {item['cancer_condition']} as no oncotree diagnosis was returned")
                continue
            child_oncotree_values = l1_to_all_mapping[item['oncotree_value']]
            nct_condition = item['cancer_condition']
            logger.debug(f"NCTID: {nct_id} | Stage 3 - Condition = {nct_condition}. Child values = {child_oncotree_values}")
            if len(child_oncotree_values) > 0:
                oncotree_diagnoses_result = ai.get_child_level_diagnoses_from_condition(nct_id, child_oncotree_values, nct_condition)
                if oncotree_diagnoses_result and 'oncotree_diagnoses' in oncotree_diagnoses_result.keys():
                    all_possible_diagnoses.update(oncotree_diagnoses_result['oncotree_diagnoses'])

        if len(all_possible_diagnoses) == 0:
            logger.info(f"NCTID: {nct_id} | No oncotree diagnosis was found from original conditions, trying from keywords and title")
            extra_info = []
            keywords = get_nct_keywords(trial_data)
            if keywords:
                extra_info.extend(keywords)
            long_title = tdh.safe_get(trial_data, ['protocolSection', 'identificationModule', 'officialTitle'])
            brief_title = tdh.safe_get(trial_data, ['protocolSection', 'identificationModule', 'briefTitle'])
            extra_info.append(long_title)
            extra_info.append(brief_title)

            all_level_oncotree_values = set()
            level1_oncotree_values_dict = ai.get_oncotree_diagnoses_from_trial_info(nct_id, extra_info, level_1_diagnosis)
            level1_diagnoses = level1_oncotree_values_dict.get("oncotree_diagnoses", [])
            if not level1_diagnoses:
                logger.debug(f"NCTID: {nct_id} | No level 1 diagnoses from keywords/title, skipping child-level mapping")
            else:
                for item in level1_diagnoses:
                    if item == "" or item.lower() == "other":
                        continue
                    child_oncotree_values = l1_to_all_mapping[item]
                    all_level_oncotree_values.update(child_oncotree_values)
                logger.debug(f"NCTID: {nct_id} | Stage 3 - Diagnoses = {level1_diagnoses}. Child values = {all_level_oncotree_values}")
                if all_level_oncotree_values:
                    oncotree_diagnoses_result = ai.get_oncotree_diagnoses_from_trial_info(nct_id, extra_info, all_level_oncotree_values)
                    if oncotree_diagnoses_result and 'oncotree_diagnoses' in oncotree_diagnoses_result.keys():
                        all_possible_diagnoses.update(oncotree_diagnoses_result['oncotree_diagnoses'])

    return all_possible_diagnoses

def map_global_diagnosis_to_oncotree_term(trial_data: dict, global_eligibility_criteria: str = "") -> list:
    nct_id = get_nct_id(trial_data)
    all_possible_diagnoses = set()

    # Read the trial's own condition list first. It costs no tokens, cannot
    # hallucinate, and on the curated benchmark a plain lookup of these strings
    # against Oncotree scores within 0.02 of what the 70B model achieves
    # through both LLM stages. It is a floor, not a replacement: precision is
    # high but it finds only about a third of the answers.
    conditions_list = tdh.safe_get(trial_data, ['protocolSection', 'conditionsModule', 'conditions']) or []
    seeded = rv.diagnoses_from_conditions(conditions_list)
    if seeded:
        logger.info(f"NCTID: {nct_id} | Conditions name Oncotree terms directly: {seeded}")
        all_possible_diagnoses.update(seeded)

    from_eligibility = []
    if global_eligibility_criteria and global_eligibility_criteria.strip():
        logger.info(f"NCTID: {nct_id} | Mapping global diagnosis from eligibility criteria")
        from_eligibility = map_eligibility_criteria_to_oncotree_term(
            nct_id, global_eligibility_criteria, seeded
        )
        all_possible_diagnoses.update(from_eligibility)
        # Worth seeing. The model disagreeing with a string the trial states
        # outright is the signature of the branch problem above, and it was
        # silent until now.
        overlooked = set(seeded) - set(from_eligibility)
        if overlooked:
            logger.warning(
                f"NCTID: {nct_id} | Eligibility mapping did not return {sorted(overlooked)}, "
                f"which the trial's own conditions name outright. Kept from the conditions."
            )

    if not from_eligibility:
        logger.info(f"NCTID: {nct_id} | No oncotree diagnosis from eligibility criteria, falling back to conditions and extra info")
        all_possible_diagnoses.update(_map_global_diagnosis_from_conditions_and_extra_info(trial_data))

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
    return list(all_possible_diagnoses)

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
    
    lines = eligibility_criteria.split('\n')
    begin_exclude = False
    # Populate prior_treatment_requirements
    for line in lines:
        if "Exclusion Criteria" in line:
            begin_exclude = True
        stripped_line = line.strip()
        if stripped_line:
            # Prefix exclusion criteria lines with "exclude"
            if begin_exclude:
                trial_schema['prior_treatment_requirements'].append(f'Exclude - {stripped_line}')
            else:
                # Add inclusion criteria lines directly
                trial_schema['prior_treatment_requirements'].append(stripped_line)
    return trial_schema

def split_inclusion_exclusion_criteria(trial_data: dict) -> tuple[str, str]:
    """
    Splits the eligibility criteria into inclusion and exclusion parts
    """
    eligibility_criteria = get_full_nct_eligibility_criteria(trial_data)
    inclusion_criteria, exclusion_criteria = tdh.split_with_find(eligibility_criteria, ["exclusion criteria", "exclusion"])    
    return inclusion_criteria, exclusion_criteria


 

