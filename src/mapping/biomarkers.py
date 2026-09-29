"""
Biomarker status from eligibility text, for both registries: HER2/ER/PR,
PD-L1, MMR/MS and disease status, each asked of the model only when the text
has a keyword for it.

Moved from src/clinical_trials_gov.py on 2026-09-29 (step 11, phase 2).
"""

from loguru import logger

import src.match_criteria_mapper as mcm
import utils.llm.prompts.biomarkers as biomarker_prompts


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


def map_her2_er_pr_status(nct_id: str, eligibilityCriteria: str, keywords: list):
    result = biomarker_prompts.get_her2_er_pr_status(nct_id, eligibilityCriteria, keywords)
    filtered_her2_er_pr_dict = {
        k: v
        for k, v in result.items()
        if v.lower() in ["positive", "negative", "!positive", "!negative"]
    }
    return filtered_her2_er_pr_dict


def map_pdl1_status(nct_id: str, eligibilityCriteria: str, keywords: list):
    contains_pdl1_info = mcm.check_if_eligibility_criteria_contains_pdl1_info(
        keywords, eligibilityCriteria
    )
    if contains_pdl1_info:
        result = biomarker_prompts.get_pdl1_status(nct_id, eligibilityCriteria, keywords)
        filtered_pdl1_status_dict = {
            k: v for k, v in result.items() if v.lower() in ["high", "low"]
        }
        return filtered_pdl1_status_dict
    return {}


def map_mmr_ms_status(nct_id: str, eligibilityCriteria: str, keywords: list):
    filtered_mmr_ms_status_dict = {}
    contains_mmr_info = mcm.check_if_eligibility_criteria_contains_mmr_info(
        keywords, eligibilityCriteria
    )
    if contains_mmr_info:
        mmr_ms_status_dict = biomarker_prompts.get_mmr_status(nct_id, eligibilityCriteria, keywords)
        if "mmr_status" in mmr_ms_status_dict:
            mmr_value = mmr_ms_status_dict["mmr_status"]
            if mmr_value in [
                "MMR-Proficient",
                "MMR-Deficient",
                "!MMR-Proficient",
                "!MMR-Deficient",
            ]:
                filtered_mmr_ms_status_dict["mmr_status"] = mmr_value

        if "ms_status" in mmr_ms_status_dict:
            ms_value = mmr_ms_status_dict["ms_status"]
            if ms_value in ["MSI-H", "MSI-L", "MSS", "!MSI-H", "!MSI-L"]:
                filtered_mmr_ms_status_dict["ms_status"] = ms_value
    return filtered_mmr_ms_status_dict


def map_disease_status(nct_id: str, eligibilityCriteria: str, keywords: list):
    result = biomarker_prompts.get_disease_status(nct_id, eligibilityCriteria, keywords)
    return result
