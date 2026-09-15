# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

import json
import re
import config
import requests
import urllib.parse
import utils.schema as schema
from inspect import cleandoc
from loguru import logger
from utils.llm_platforms import create_llm_platform
from utils.genomic_patterns import MUTATION_DETAIL_KEYWORDS, CNV_DETAIL_KEYWORDS

# Pre-compile patterns for efficiency
_MUTATION_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in MUTATION_DETAIL_KEYWORDS]
_CNV_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in CNV_DETAIL_KEYWORDS]


def has_mutation_details(criteria_text: str) -> bool:
    """
    Check if the criteria text contains keywords suggesting mutation details
    (variant_classification, exon) are present.
    
    Uses simple keyword/regex matching to avoid unnecessary LLM calls.
    
    Args:
        criteria_text: The eligibility criteria text to scan.
        
    Returns:
        True if mutation detail keywords are found, False otherwise.
    """
    if not criteria_text:
        return False
    
    for pattern in _MUTATION_PATTERNS:
        if pattern.search(criteria_text):
            return True
    return False


def has_cnv_details(criteria_text: str) -> bool:
    """
    Check if the criteria text contains keywords suggesting CNV details
    (cnv_call) are present.
    
    Uses simple keyword/regex matching to avoid unnecessary LLM calls.
    
    Args:
        criteria_text: The eligibility criteria text to scan.
        
    Returns:
        True if CNV detail keywords are found, False otherwise.
    """
    if not criteria_text:
        return False
    
    for pattern in _CNV_PATTERNS:
        if pattern.search(criteria_text):
            return True
    return False

# Initialize the LLM platform based on config
_llm_platform = create_llm_platform(
    platform_name=config.LLM_PLATFORM,
    model=config.LLM_AI_MODEL,
    hostname=config.GPU_SERVER_HOSTNAME
)

def get_level1_diagnosis_from_original_conditions(nct_id:str, original_conditions: dict, level1_oncotree: set) -> dict:    
    original_conditions_list = list(original_conditions)
    level1_oncotree_list = list(level1_oncotree) 
    
    schema, prompt = get_ai_prompt_level1_for_original_conditions(original_conditions_list, level1_oncotree_list)

    logger.debug(f"NCTID: {nct_id} | AI Prompt for Level 1 diagnosis from original conditions: {prompt}")
        
    ai_response = send_ai_request(nct_id, prompt, schema)
    oncotree_diagnoses_dict = parse_ai_response(ai_response)
    return oncotree_diagnoses_dict

def get_oncotree_diagnoses_from_trial_info(nct_id: str, trial_info, oncotree_values: set) -> dict:
    schema, prompt = get_ai_prompt_oncotree_diagnoses_from_trial_info(trial_info, list(oncotree_values))
    ai_response = send_ai_request(nct_id, prompt, schema)
    return parse_ai_response(ai_response)

def get_child_level_diagnoses_from_condition(nct_id:str, child_nodes_oncotree:set, nct_condition: str) -> dict:
    child_nodes_oncotree_list = list(child_nodes_oncotree)

    schema, prompt = get_ai_prompt_child_values(nct_condition, child_nodes_oncotree_list)

    ai_response = send_ai_request(nct_id, prompt, schema)
    oncotree_diagnoses_dict = parse_ai_response(ai_response)   
    return oncotree_diagnoses_dict

def get_her2_er_pr_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_her2_er_pr_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    her2_er_pr_status_dict = parse_ai_response(ai_response)   
    return her2_er_pr_status_dict

def get_pdl1_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_pdl1_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    pdl1_status_dict = parse_ai_response(ai_response)   
    return pdl1_status_dict

def get_mmr_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_mmr_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    mmr_status_dict = parse_ai_response(ai_response)   
    return mmr_status_dict

def get_disease_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_disease_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    disease_status_dict = parse_ai_response(ai_response)   
    return disease_status_dict


def get_minimum_age(nct_id: str, inclusion_criteria: str) -> dict:
    """
    Read the minimum eligible age out of free-text criteria.

    ClinicalTrials.gov publishes a structured minimumAge field; CTIS does not,
    and the text is too varied for a pattern ("Age >=1 and <80 years",
    "Patients aged 1 to <=21 years", "Children between 1 year (>= 12 months)
    and 18 years"). It also contains ages that are not eligibility bounds at
    all, such as the Karnofsky/Lansky split at 16 years, which a pattern
    reliably mistakes for one.
    """
    schema, prompt = get_minimum_age_prompt(inclusion_criteria)
    ai_response = send_ai_request(nct_id, prompt, schema)
    return parse_ai_response(ai_response)


def get_arm_criteria_mapping(nct_id: str, arm_groups: list, inclusion_criteria: str, exclusion_criteria: str) -> dict:
    """
    Call the LLM to classify eligibility criteria into global vs per-arm text.

    Args:
        nct_id: Trial identifier for logging.
        arm_groups: The raw ClinicalTrials.gov armGroups list
                    (from protocolSection.armsInterventionsModule.armGroups).
        inclusion_criteria: Full inclusion criteria text for the trial.
        exclusion_criteria: Full exclusion criteria text for the trial.

    Returns:
        A JSON-like dict describing:
        - global: text that applies to all arms.
        - arms: per-arm snippets keyed by arm label, which will later be
          normalized into arm_criteria_blocks keyed by CTML arm identifiers.
    """
    prompt = get_arm_criteria_mapping_prompt(
        arm_groups=arm_groups,
        inclusion_criteria=inclusion_criteria,
        exclusion_criteria=exclusion_criteria,
    )
    # Intentionally call the model without a JSON schema for now and rely on its
    # natural JSON output.
    ai_response = send_ai_request(nct_id, prompt)
    mapping = parse_ai_response(ai_response)
    return mapping

def get_inclusion_genomic_criteria(nct_id:str, genes:list, eligibilityCriteria:str)-> list:
    json_schema, prompt = get_inclusion_genomic_criteria_prompt(genes, eligibilityCriteria)
    ai_response = send_ai_request(nct_id, prompt, json_schema)
    genomic_criteria = parse_ai_response(ai_response)
    return genomic_criteria

def get_exclusion_genomic_criteria(nct_id:str, genes:list, eligibilityCriteria:str)-> list:
    json_schema, prompt = get_exclusion_genomic_criteria_prompt(genes, eligibilityCriteria)
    ai_response = send_ai_request(nct_id, prompt, json_schema)
    genomic_criteria = parse_ai_response(ai_response)
    return genomic_criteria


def enrich_mutation_details(nct_id: str, mutation_criteria: list, criteria_text: str) -> list:
    """
    Enrich mutation criteria with variant_classification and/or exon details.

    This function performs a second-pass LLM call to extract additional mutation
    details for entries already identified as having Mutations. The model is given
    the full `mutation_criteria` list and asked to return enrichment objects that
    reference specific entries by their index in that list, so that multiple
    mutations for the same gene can be enriched independently.
    
    Args:
        nct_id: The clinical trial identifier for logging.
        mutation_criteria: List of genomic criteria dicts that have variant_category="Mutation".
                           Each dict should have a "genomic" key with "hugo_symbol".
        criteria_text: The original eligibility criteria text to analyze.
        
    Returns:
        List of enrichment dicts with format:
        [{"index": int, "variant_classification": "type_or_null", "exon": int_or_null}, ...]
        Returns empty list if enrichment fails or no mutations to enrich.
    """
    if not mutation_criteria or not criteria_text:
        return []
    
    genes_with_mutations = []
    for criterion in mutation_criteria:
        genomic = criterion.get("genomic", {})
        hugo_symbol = genomic.get("hugo_symbol")
        if hugo_symbol:
            genes_with_mutations.append(hugo_symbol)
    
    if not genes_with_mutations:
        return []
    
    logger.info(f"NCTID: {nct_id} | Enriching mutation details for genes: {genes_with_mutations}")
    
    json_schema, prompt = get_mutation_detail_enrichment_prompt(
        genes_with_mutations, criteria_text, mutation_criteria
    )
    
    try:
        ai_response = send_ai_request(nct_id, prompt, json_schema)
        enrichment_result = parse_ai_response(ai_response)
        
        if isinstance(enrichment_result, dict):
            enriched_mutations = enrichment_result.get("enriched_mutations", [])
        elif isinstance(enrichment_result, list):
            enriched_mutations = enrichment_result
        else:
            logger.warning(f"NCTID: {nct_id} | Unexpected enrichment response format: {type(enrichment_result)}")
            return []
        
        logger.info(f"NCTID: {nct_id} | Mutation enrichment result: {enriched_mutations}")
        return enriched_mutations
        
    except Exception as e:
        logger.error(f"NCTID: {nct_id} | Mutation enrichment failed: {e}")
        return []


def enrich_cnv_details(nct_id: str, cnv_criteria: list, criteria_text: str) -> list:
    """
    Enrich CNV criteria with cnv_call details.
    
    This function performs a second-pass LLM call to extract the specific CNV type
    for genes already identified as having Copy Number Variations.
    
    Args:
        nct_id: The clinical trial identifier for logging.
        cnv_criteria: List of genomic criteria dicts that have variant_category="Copy Number Variation".
                     Each dict should have a "genomic" key with "hugo_symbol".
        criteria_text: The original eligibility criteria text to analyze.
        
    Returns:
        List of enrichment dicts with format:
        [{"hugo_symbol": "GENE", "cnv_call": "type_or_null"}, ...]
        Returns empty list if enrichment fails or no CNVs to enrich.
    """
    if not cnv_criteria or not criteria_text:
        return []
    
    genes_with_cnv = []
    for criterion in cnv_criteria:
        genomic = criterion.get("genomic", {})
        hugo_symbol = genomic.get("hugo_symbol")
        if hugo_symbol:
            genes_with_cnv.append(hugo_symbol)
    
    if not genes_with_cnv:
        return []
    
    logger.info(f"NCTID: {nct_id} | Enriching CNV details for genes: {genes_with_cnv}")
    
    json_schema, prompt = get_cnv_detail_enrichment_prompt(
        genes_with_cnv, criteria_text, cnv_criteria
    )
    
    try:
        ai_response = send_ai_request(nct_id, prompt, json_schema)
        enrichment_result = parse_ai_response(ai_response)
        
        if isinstance(enrichment_result, dict):
            enriched_cnvs = enrichment_result.get("enriched_cnvs", [])
        elif isinstance(enrichment_result, list):
            enriched_cnvs = enrichment_result
        else:
            logger.warning(f"NCTID: {nct_id} | Unexpected CNV enrichment response format: {type(enrichment_result)}")
            return []
        
        logger.info(f"NCTID: {nct_id} | CNV enrichment result: {enriched_cnvs}")
        return enriched_cnvs
        
    except Exception as e:
        logger.error(f"NCTID: {nct_id} | CNV enrichment failed: {e}")
        return []

def parse_ai_response(ai_response):
    return _llm_platform.parse_response(ai_response)

def send_ai_request(id, prompt, json_schema=None):
    """Send AI request using the configured platform."""
    # Hosted platforms (e.g. Anthropic) own their transport and auth via an
    # official SDK, so they expose send() instead of going through the
    # unauthenticated hostname:port POST used by the self-hosted platforms.
    sender = getattr(_llm_platform, 'send', None)
    if callable(sender):
        logger.debug(f"AI request | ID:{id} | {prompt[:200]}")
        ai_response = sender(prompt, json_schema)
        logger.debug(f"AI response | ID:{id} | {ai_response}")
        return ai_response

    req_body = _llm_platform.get_request_body(prompt, json_schema)
    req_body_json = json.dumps(req_body)
    logger.debug(f"AI request | ID:{id} | {req_body_json}")
    endpoint_url = _llm_platform.get_endpoint_url()
    print(endpoint_url)

    # Without a timeout a stalled or runaway model blocks the pipeline forever:
    # a local 14B in a constrained-JSON generation loop was observed emitting
    # 30k+ tokens over 3.5 hours on a single call.
    timeout = getattr(config, 'LLM_REQUEST_TIMEOUT_SECONDS', 600)
    response = requests.post(endpoint_url, data=req_body_json,
                             headers={"Content-Type": "application/json"},
                             timeout=timeout)

    response.raise_for_status()

    print(response.status_code)
    ai_response = response.json()
    logger.debug(f"AI response | ID:{id} | {ai_response}")
    return ai_response

def get_ai_prompt_level1_for_original_conditions(original_conditions_list, level1_oncotree_list):
    prompt = f"""Task: Map CancerConditions to the closest cancer type in OncotreeValues.
        CancerConditions: {original_conditions_list}
        OncotreeValues: {level1_oncotree_list}
        Output in JSON format:
        {{
        "oncotree_diagnoses": [
            {{
            "cancer_condition": "",
            "oncotree_value": ""
            }}
        ]
        }}"""
    return level1_diagnoses_schema(level1_oncotree_list), cleandoc(prompt)

def get_ai_prompt_oncotree_diagnoses_from_trial_info(trial_info, oncotree_values):
    prompt = f"""Task: From the TrialInfo, extract OncotreeValues that correspond to medical conditions explicitly mentioned in the text.
        Rules:
        - Only include a diagnosis if the condition or cancer type is explicitly stated in TrialInfo.
        - Do not infer diagnoses from drug names, treatment regimens, parent studies, or other indirect clues.
        - If no condition or cancer type is explicitly mentioned, return an empty list.
        - Choose only from the provided OncotreeValues.

        TrialInfo: {trial_info}
        OncotreeValues: {oncotree_values}

        Output in JSON format:
        {{
        "oncotree_diagnoses": []
        }}"""

    return oncotree_diagnoses_schema(oncotree_values), cleandoc(prompt)

def get_ai_prompt_child_values(nct_condition, child_nodes_oncotree_list):

    # cancer_condition: {nct_condition} E.g. -> Colorectal Cancer
    # Oncotree values: {child_nodes_oncotree} # E.g. -> {'Signet Ring Cell Adenocarcinoma of the Colon and Rectum', 'Colon Adenocarcinoma In Situ', 'Small Bowel Well-Differentiated Neuroendocrine Tumor', 'Gastrointestinal Neuroendocrine Tumors', 'Well-Differentiated Neuroendocrine Tumor of the Rectum', 'Small Bowel Cancer', 'Anal Squamous Cell Carcinoma', 'Anorectal Mucosal Melanoma', 'Low-grade Appendiceal Mucinous Neoplasm', 'Medullary Carcinoma of the Colon', 'Goblet Cell Adenocarcinoma of the Appendix', 'Mucinous Adenocarcinoma of the Appendix', 'Appendiceal Adenocarcinoma', 'Small Intestinal Carcinoma', 'Well-Differentiated Neuroendocrine Tumor of the Appendix', 'Signet Ring Cell Type of the Appendix', 'Colorectal Adenocarcinoma', 'High-Grade Neuroendocrine Carcinoma of the Colon and Rectum', 'Colonic Type Adenocarcinoma of the Appendix', 'Anal Gland Adenocarcinoma', 'Rectal Adenocarcinoma', 'Mucinous Adenocarcinoma of the Colon and Rectum', 'Duodenal Adenocarcinoma', 'Colon Adenocarcinoma', 'Tubular Adenoma of the Colon'}

    prompt = f"""
        Task: Map CancerCondition to the closest cancer diagnoses in OncotreeValues.
        CancerCondition: {nct_condition}
        OncotreeValues: {child_nodes_oncotree_list}

        Output in JSON format:
        {{
        "cancer_condition": "",
        "oncotree_diagnoses": []
        }}
        """
    return child_values_schema(child_nodes_oncotree_list), cleandoc(prompt)

def get_her2_er_pr_status_prompt(eligibilityCriteria, keywords):
    prompt = f"""
        Task: From the EligibilityCriteria and TrialKeywords, return the required Her2, PR or ER status.
        Use the '!' operator if the criteria excludes a status.
        EligibilityCriteria: {eligibilityCriteria}
        TrialKeywords: {keywords}

        Output in JSON format:
        {{
        "her2_status": "value",
        "er_status": "value",
        "pr_status": "value"
        }}
        where "value" must be in ["Positive", "Negative", "Unknown", "!Positive", "!Negative"]
        """
    return HER2_ER_PR_SCHEMA, cleandoc(prompt)

def get_pdl1_status_prompt(eligibilityCriteria, keywords):
    prompt = f"""
        Task: From the EligibilityCriteria and TrialKeywords, return the required PDL1 (PD-L1) status.
        EligibilityCriteria: {eligibilityCriteria}
        TrialKeywords: {keywords}

        Output in JSON format:
        {{
        "pdl1_status": "value",
        }}
        where "value" is in ["High", "Low", "Unknown"].
        """
    return PDL1_SCHEMA, cleandoc(prompt)

def get_mmr_status_prompt(eligibilityCriteria, keywords):
    prompt = f"""
        Task: From the EligibilityCriteria and TrialKeywords, return the required mismatch repair (MMR) and/or microsatellite (MS) status;
        return an empty JSON if the text does not mention MMR or MS status.
        EligibilityCriteria: {eligibilityCriteria}
        TrialKeywords: {keywords}

        Output in JSON format:
        {{
        "mmr_status": "value1",
        "ms_status": "value2"
        }}
        where "value1" is in ["MMR-Proficient", "MMR-Deficient",'!MMR-Proficient', '!MMR-Deficient']. 
        and "value2" is in ['MSI-H', 'MSI-L', 'MSS','!MSI-H', '!MSI-L'].
        """
    return MMR_MS_SCHEMA, cleandoc(prompt)

def get_disease_status_prompt(eligibilityCriteria, keywords):
    prompt = f"""Task: From the EligibilityCriteria and TrialKeywords, return the required disease statuses of the cancer.
        EligibilityCriteria: {eligibilityCriteria}
        TrialKeywords: {keywords}

        Output in JSON format:
        {{
        "disease_status": [],
        }}
        where each disease_status is in ["Untreated", "Localized", "Locally Advanced", "Metastatic", "Advanced", "Recurrent", "Refractory", "Unresectable", "Early Stage"].
        """
    return DISEASE_STATUS_SCHEMA, cleandoc(prompt)


def get_minimum_age_prompt(inclusion_criteria):
    prompt = f"""Task: From the InclusionCriteria, find the minimum age a participant must be to be eligible.

        InclusionCriteria: {inclusion_criteria}

        Rules:
        - Report only an age a participant must MEET OR EXCEED to enrol.
        - Ignore ages that are not eligibility limits, for example the age at
          which a different performance scale is used (Karnofsky vs Lansky),
          the age at original diagnosis when enrolment age differs, or ages
          appearing in exclusion or dosing text.
        - Ignore maximum ages entirely.
        - Convert to years: 12 months = 1, 6 months = 0.5, 28 days = 0.08.
        - If the criteria state no minimum age, return null.

        Output in JSON format:
        {{
        "minimum_age_years": null
        }}
        where minimum_age_years is a number or null.
        """
    return MINIMUM_AGE_SCHEMA, cleandoc(prompt)


def get_arm_criteria_mapping_prompt(arm_groups: list, inclusion_criteria: str, exclusion_criteria: str) -> str:
    """
    Build a focused prompt for mapping global vs per-arm eligibility criteria.

    The model is asked to:
    - Identify text that truly applies to all arms (global).
    - Identify text that clearly applies only to specific arms.
    - Associate per-arm snippets back to arms using their labels/descriptions.
    """
    # Keep the raw armGroups structure visible to the model so it can use labels,
    # descriptions, and interventions to anchor references.
    arms_groups_json = json.dumps(arm_groups, indent=2)

    prompt = f"""
        You are helping to map clinical trial eligibility criteria to specific treatment arms.

        The trial has the following arms:
        - arm_groups:
        {arms_groups_json}

        The full eligibility criteria text is split into:
        - InclusionCriteria:
        {inclusion_criteria}

        - ExclusionCriteria:
        {exclusion_criteria}

        Your tasks:
        1. Extract lines of eligibility criteria text that:
           - Apply to ALL arms (global).
           - Apply ONLY to a specific arm or set of arms.
           Focus on clear, explicit associations (e.g., arm labels such as
           "Cohort A", "Arm 1", or descriptions that obviously match a single arm).

        2. For each arm, use the "label" field from arm_groups as the canonical
           identifier in the output (arm_label). It MUST match the arm_groups[i].label
           value exactly so we can map it back later.

        3. If an arm only uses global criteria and has no extra arm-specific text,
           return empty strings for its inclusion_text and/or exclusion_text.

        IMPORTANT:
        - Do NOT change or "improve" the wording of the criteria; copy exact text
          snippets from the inclusion/exclusion text.
        - Do NOT invent extra arms; only use arms that appear in the input JSON.
        - If a snippet clearly applies to multiple arms, you may repeat it in each
          applicable arm's inclusion_text/exclusion_text.

        Output a single JSON object with the following shape:
        {{
          "global": {{
            "inclusion_text": "text that truly applies to all arms (may be empty)",
            "exclusion_text": "text that truly applies to all arms (may be empty)"
          }},
          "arms": [
            {{
              "arm_label": "EXACT arm label string from arm_groups[i].label",
              "inclusion_text": "text that applies only to this arm (or empty string)",
              "exclusion_text": "text that applies only to this arm (or empty string)"
            }}
          ]
        }}
    """

    return cleandoc(prompt)

# a lot of trial criteria mention exclusion too in inclusion criteria hence the prompt supplies both inclusion and exclusion instructions
# Shape that _enrich_genomic_criteria expects. Supplied to Ollama as
# "format", which constrains decoding rather than merely asking for JSON.
# Without it a model will happily echo the prompt's own input labels back as
# keys - gemma3:27b returned {"EligibilityCriteria": ..., "Possible GeneList":
# [], "Output": []} on 8 of 12 benchmark trials, treating the prompt as a
# template to fill in.
# Structured output for everything the model is asked for, not just genomic
# criteria. Without it Ollama is free to return prose or malformed JSON, and
# parse_response logs a JSONDecodeError and hands back an empty dict - so the
# whole answer is discarded as if the model had found nothing. Observed twice
# on a single trial: "Expecting ',' delimiter: line 68 column 1 (char 514)",
# which is 68 lines in 514 characters, i.e. a list of diagnoses one per line
# with the commas missing.
#
# Where the prompt already restricts the answer to a list of candidates, the
# schema restricts it too, which makes an off-list answer impossible to emit
# rather than merely discouraged. "Lymphoma" and "_SOLID_" are not Oncotree
# display names and cannot be produced under these schemas at all.

# Ollama compiles `format` into a generation grammar, and one with several
# hundred alternatives is slow to build. Above this many candidates the enum is
# dropped and the schema still guarantees well-formed JSON of the right shape.
# The cap is a guard, not a tuned value - it has not been measured on the GPU.
_MAX_ENUM_VALUES = 400


def _one_of(allowed, extra=()):
    """A string constrained to `allowed`, or an unconstrained one if too many."""
    values = sorted({a for a in list(allowed) + list(extra) if a is not None})
    if values and len(values) <= _MAX_ENUM_VALUES:
        return {"type": "string", "enum": values}
    return {"type": "string"}


def oncotree_diagnoses_schema(allowed):
    return {
        "type": "object",
        "properties": {"oncotree_diagnoses": {"type": "array",
                                              "items": _one_of(allowed)}},
        "required": ["oncotree_diagnoses"],
    }


def level1_diagnoses_schema(allowed):
    # "" and "Other" are how the caller is told a condition has no level_1, and
    # clinical_trials_gov skips exactly those two. They must stay sayable, or a
    # constrained model is forced to pick a branch it does not believe in.
    return {
        "type": "object",
        "properties": {"oncotree_diagnoses": {"type": "array", "items": {
            "type": "object",
            "properties": {"cancer_condition": {"type": "string"},
                           "oncotree_value": _one_of(allowed, ("", "Other"))},
            "required": ["cancer_condition", "oncotree_value"],
        }}},
        "required": ["oncotree_diagnoses"],
    }


def child_values_schema(allowed):
    return {
        "type": "object",
        "properties": {"cancer_condition": {"type": "string"},
                       "oncotree_diagnoses": {"type": "array",
                                              "items": _one_of(allowed)}},
        "required": ["oncotree_diagnoses"],
    }


_RECEPTOR_VALUES = ["Positive", "Negative", "Unknown", "!Positive", "!Negative"]
HER2_ER_PR_SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "string", "enum": _RECEPTOR_VALUES}
                   for name in ("her2_status", "er_status", "pr_status")},
    "required": ["her2_status", "er_status", "pr_status"],
}

PDL1_SCHEMA = {
    "type": "object",
    "properties": {"pdl1_status": {"type": "string",
                                   "enum": ["High", "Low", "Unknown"]}},
    "required": ["pdl1_status"],
}

# No "Unknown" here, so neither field is required: forcing a choice between
# proficient and deficient would invent one.
MMR_MS_SCHEMA = {
    "type": "object",
    "properties": {
        "mmr_status": {"type": "string", "enum": [
            "MMR-Proficient", "MMR-Deficient", "!MMR-Proficient", "!MMR-Deficient"]},
        "ms_status": {"type": "string", "enum": [
            "MSI-H", "MSI-L", "MSS", "!MSI-H", "!MSI-L"]},
    },
}

DISEASE_STATUS_SCHEMA = {
    "type": "object",
    "properties": {"disease_status": {"type": "array", "items": {
        "type": "string", "enum": [
            "Untreated", "Localized", "Locally Advanced", "Metastatic",
            "Advanced", "Recurrent", "Refractory", "Unresectable", "Early Stage"]}}},
    "required": ["disease_status"],
}

MINIMUM_AGE_SCHEMA = {
    "type": "object",
    "properties": {"minimum_age_years": {"type": ["number", "null"]}},
    "required": ["minimum_age_years"],
}


GENOMIC_CRITERIA_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "genomic": {
                "type": "object",
                "properties": {
                    "hugo_symbol": {"type": "string"},
                    "variant_category": {
                        "type": "string",
                        "enum": [
                            "Mutation", "Copy Number Variation",
                            "Structural Variation", "Any Variation",
                            "!Mutation", "!Copy Number Variation",
                            "!Structural Variation", "!Any Variation",
                        ],
                    },
                    "protein_change": {"type": "string"},
                    "cnv_call": {
                        "type": "string",
                        "enum": [
                            "Low Amplification", "High Amplification",
                            "Homozygous Deletion", "Heterozygous Deletion",
                            "!Low Amplification", "!High Amplification",
                            "!Homozygous Deletion", "!Heterozygous Deletion",
                        ],
                    },
                },
                "required": ["hugo_symbol", "variant_category"],
            }
        },
        "required": ["genomic"],
    },
}


def get_inclusion_genomic_criteria_prompt(genes, inclusion_criteria):
    prompt = f"""Task: Evaluate the clinical trial criteria to return a JSON-formatted eligibility criteria involving genetic variants in any genes such as those in the GeneList.
    EligibilityCritieria: {inclusion_criteria}
    Possible GeneList: {genes}

    Output in JSON format such that:
    1. "variant_category" must be in ["Mutation", "Copy Number Variation", "Structural Variation", "Any Variation","!Mutation", "!Copy Number Variation", "!Structural Variation", "!Any Variation"],
       where "Mutation" is defined narrowly to include only single nucleotide variants (SNVs) and indels.
    2. If a specific amino acid substitution is explicitly mentioned for point mutations, return it in the "protein_change" field, with  format "p.XnnY" (e.g., p.G12C).
    3. In EligibilityCriteria, the term "mutant" means "Any Variation", with some exceptions, such as in the context of mutations (meaning "Mutation") in EGFR and HER2 in response to targeted therapy.
    4. Include any genes that may not be present in the provided GeneList if they are clearly indicated in the criteria.
    5. If the criteria mentions only protein expression (e.g., "negative PD-L1 expression", "nPKCδ expression") without explicitly mentioning the corresponding gene name, DO NOT infer or add a gene to the output.
    6. Do not infer or add genes from disease names, cancer types, histologies, syndromes, or other conditions. Only include genes that are explicitly mentioned in the criteria text itself.
    7. Do not use known disease-to-gene associations to guess a gene when the gene name is not written in the criteria. For example, do not infer BRCA1/2 from "breast cancer", KRAS/BRAF from "colorectal cancer", or EGFR from "glioblastoma" unless the gene name is explicitly present.
    8. Output should be a list of dictionaries with each genetic alteration under a separate "genomic" key, as in the provided example. No wrapper objects, no extra keys or explanation.
    
    *CRITICAL RULE:** If the `EligibilityCriteria` only mentions a gene or variant **in the context of a patient *receiving treatment* for it** (e.g., "Have received prior treatment with any KRAS G12C", "currently on EGFR TKI therapy"), you must **EXCLUDE that gene/variant from the output entirely.**
    Only include genetic states that are direct reasons for inclusion (e.g., "patients *with* a BRAF V600E mutation are included").
    Example 1:
    Criteria: Subjects with advanced solid tumors harboring NTRK1 rearrangement or KRAS G12C will be included in this trial. 
    Output:
    [
        {{
            "genomic": {{
                "hugo_symbol": "NTRK1",
                "variant_category": "Structural Variation"
            }}
        }},
        {{
            "genomic": {{
                "hugo_symbol": "KRAS",
                "variant_category": "Mutation",
                "protein_change": "p.G12C"
            }}
        }}
    ]

    Example 2:
    Criteria: Any solid tumor type with MET amplification and negative test results for epidermal growth factor receptor (EGFR) and
      proto-oncogene1 (ROS1) actionable genomic alterations based on analysis of tumor tissue.
    Output:
    [
        {{
            "genomic": {{
                "hugo_symbol": "MET",
                "variant_category": "Copy Number Variation"
            }}
        }},
        {{
            "genomic": {{
                "hugo_symbol": "EGFR",
                "variant_category": "!Any Variation"
            }}
        }},
        {{
            "genomic": {{
                "hugo_symbol": "ROS1",
                "variant_category": "!Any Variation"
            }}
        }}
    ]
    """
    return GENOMIC_CRITERIA_SCHEMA, cleandoc(prompt)

def get_exclusion_genomic_criteria_prompt(genes, exclusion_criteria):
    prompt = f"""Task: Evaluate the clinical trial exclusion criteria to return a JSON-formatted eligibility criteria involving genetic 
    variants in any genes such as those in the GeneList.
    EligibilityCritieria: {exclusion_criteria}
    Possible GeneList: {genes}

    Output in JSON format such that:
    1. "variant_category" must be in ["!Mutation", "!Copy Number Variation", "!Structural Variation", "!Any Variation"],
       where "Mutation" is defined narrowly to include only single nucleotide variants (SNVs) and indels.
    2. If a specific amino acid substitution is explicitly mentioned mentioned for point mutations, return it in the "protein_change" field, with  format "p.XnnY" (e.g., p.G12C).
    3. In EligibilityCriteria, the term "mutant" means "Any Variation", with some exceptions, such as in the context of mutations (meaning "Mutation") in EGFR and HER2 in response to targeted therapy.  
    4. Include any genes that may not be present in the provided GeneList if they are clearly indicated in the criteria.
    5. If the criteria mentions only protein expression (e.g., "negative PD-L1 expression", "nPKCδ expression") without explicitly mentioning the corresponding gene name, DO NOT infer or add a gene to the output.
    6. Do not infer or add genes from disease names, cancer types, histologies, syndromes, or other conditions. Only include genes that are explicitly mentioned in the criteria text itself.
    7. Do not use known disease-to-gene associations to guess a gene when the gene name is not written in the criteria. For example, do not infer BRCA1/2 from "breast cancer", KRAS/BRAF from "colorectal cancer", or EGFR from "glioblastoma" unless the gene name is explicitly present.
    8. Output should be a list of dictionaries with each genetic alteration under a separate "genomic" key, as in the provided example. No wrapper objects, no extra keys or explanation.

    *CRITICAL RULES:**1. If the `EligibilityCriteria` only mentions a gene or variant **in the context of a patient *receiving treatment* for it** (e.g., "Have received prior treatment with any KRAS G12C", "currently on EGFR TKI therapy"), you must **EXCLUDE that gene/variant from the output entirely. 2. Output must follow the JSON structure as the example below.**
    Only include genetic states that are direct reasons for exclusion (e.g., "patients *with* a BRAF V600E mutation are excluded").

    Example 1:
    Criteria: Exclude - Patients who have EGFR, ALK or ROS1 driver mutations
    Output:
    [
        {{
            "genomic": {{
                "hugo_symbol": "EGFR",
                "variant_category": "!Any Variation"
            }}
        }},
        {{
            "genomic": {{
                "hugo_symbol": "ALK",
                "variant_category": "!Any Variation"
            }}
        }},
        {{
            "genomic": {{
                "hugo_symbol": "ROS1",
                "variant_category": "!Any Variation"
            }}
        }}
    ]

    """
    return GENOMIC_CRITERIA_SCHEMA, cleandoc(prompt)


def get_mutation_detail_enrichment_prompt(genes_with_mutations: list, criteria_text: str, existing_criteria: list) -> tuple:
    """
    Generate a focused prompt to enrich mutation criteria with variant_classification and exon details.
    Args:
        genes_with_mutations: List of HUGO gene symbols identified as having Mutations.
        criteria_text: The original eligibility criteria text.
        existing_criteria: The current mutation genomic criteria output from the initial extraction
                           (only the mutation entries that may need enrichment).        
    Returns:
        Tuple of (json_schema, prompt_string).
    """
    prompt = f"""Task: Enrich the existing list of mutation genomic criteria with additional details
    (variant_classification and exon) using the EligibilityCriteria text.
    
    Genes with mutations: {genes_with_mutations}
    EligibilityCriteria: {criteria_text}
    
    CurrentMutationCriteria (LIST TO ENRICH; index positions are important):
    {json.dumps(existing_criteria, indent=2)}
    
    For each entry in CurrentMutationCriteria, you MAY determine:
    1. "variant_classification": The specific type of mutation, if mentioned. Must be one of:
       - "In_Frame_Del" - for exon deletions, in-frame deletions (e.g., EGFR exon 19 deletion)
       - "In_Frame_Ins" - for exon insertions, in-frame insertions (e.g., EGFR exon 20 insertion)
       - "Splice_Site" - for splice site mutations, exon skipping (e.g., MET exon 14 skipping)
       - "Missense_Mutation" - for point mutations with amino acid change
       - "Nonsense_Mutation" - for truncating/stop codon mutations
       - "Frame_Shift_Del" - for frameshift deletions
       - "Frame_Shift_Ins" - for frameshift insertions
       - null if not specified or unclear
    2. "exon": The exon number as an integer, if explicitly mentioned (e.g., 19, 20, 14). Return null if not specified.
    
    IMPORTANT RULES:
    - OUTPUT MUST REFER TO SPECIFIC ENTRIES BY THEIR INDEX IN CurrentMutationCriteria.
    - Use the same list index as shown in CurrentMutationCriteria (0-based Python list index).
    - If multiple mutations for the same gene exist (e.g., EGFR Ex19del and EGFR L858R),
      ONLY enrich the entry whose mutation is actually associated with the exon detail.
      Do NOT copy exon details or variant_classification to other entries for the same gene
      unless the criteria text clearly applies to them as well.
    - Only extract details that are EXPLICITLY mentioned in the criteria text.
    - Do NOT infer variant_classification from protein_change alone.
    - If no additional details can be extracted for a given entry, either omit it from the output
      or return null values for that entry.
    
    Example 1:
    CurrentMutationCriteria:
    [
      {{"genomic": {{"hugo_symbol": "EGFR", "variant_category": "Mutation"}}}},
      {{"genomic": {{"hugo_symbol": "EGFR", "variant_category": "Mutation", "protein_change": "p.L858R"}}}}
    ]
    Criteria mentions "EGFR exon 19 deletion" and "L858R" with no exon.
    Valid output:
    {{
      "enriched_mutations": [
        {{"index": 0, "variant_classification": "In_Frame_Del", "exon": 19}},
        {{"index": 1, "variant_classification": "Missense_Mutation", "exon": null}}
      ]
    }}
    
    Example 2:
    Criteria mentions "MET exon 14 skipping mutation".
    Valid output for a single MET mutation entry at index 0:
    {{
      "enriched_mutations": [
        {{"index": 0, "variant_classification": "Splice_Site", "exon": 14}}
      ]
    }}
    
    Output in JSON format:
    {{
      "enriched_mutations": [
        {{
          "index": INDEX_IN_CurrentMutationCriteria,
          "variant_classification": "classification_or_null",
          "exon": exon_number_or_null
        }}
      ]
    }}
    """
    json_schema = None
    return json_schema, cleandoc(prompt)


def get_cnv_detail_enrichment_prompt(genes_with_cnv: list, criteria_text: str, existing_criteria: list) -> tuple:
    """
    Generate a focused prompt to enrich CNV criteria with cnv_call details.
    Args:
        genes_with_cnv: List of HUGO gene symbols identified as having CNVs.
        criteria_text: The original eligibility criteria text.
        existing_criteria: The current CNV genomic criteria output from the initial extraction
                           (only the CNV entries that may need enrichment).        
    Returns:
        Tuple of (json_schema, prompt_string).
    """
    prompt = f"""Task: Enrich the existing list of copy number variation (CNV) genomic criteria with
    the specific cnv_call type using the EligibilityCriteria text.
    
    Genes with CNVs: {genes_with_cnv}
    EligibilityCriteria: {criteria_text}
    
    CurrentCNVCriteria (LIST TO ENRICH; index positions are important):
    {json.dumps(existing_criteria, indent=2)}
    
    For each entry in CurrentCNVCriteria, you MAY determine "cnv_call": The specific type of copy
    number variation. Must be one of:
    - "High Amplification" - for high-level amplification, strong amplification
    - "Low Amplification" - for low-level amplification, modest amplification
    - "Homozygous Deletion" - for homozygous deletion, complete loss, biallelic loss
    - "Heterozygous Deletion" - for heterozygous deletion, single copy loss
    - null if CNV type is not specified or unclear
    
    IMPORTANT RULES:
    - OUTPUT MUST REFER TO SPECIFIC ENTRIES BY THEIR INDEX IN CurrentCNVCriteria.
    - Use the same list index as shown in CurrentCNVCriteria (0-based Python list index).
    - Only extract details that are EXPLICITLY mentioned in the criteria text.
    - Terms like "deficient", "deficiency", or "loss of expression" typically indicate "Homozygous Deletion".
    - If no additional details can be extracted for a given entry, either omit it from the output
      or return null cnv_call for that entry.
    
    Example 1:
    Criteria mentions "MET amplification" and there is a single MET CNV entry at index 0:
    {{
      "enriched_cnvs": [
        {{"index": 0, "cnv_call": "High Amplification"}}
      ]
    }}
    
    Output in JSON format:
    {{
      "enriched_cnvs": [
        {{
          "index": INDEX_IN_CurrentCNVCriteria,
          "cnv_call": "cnv_type_or_null"
        }}
      ]
    }}
    """
    json_schema = None
    return json_schema, cleandoc(prompt)


def merge_enriched_criteria(original: list, enriched: list, enrichment_type: str = "mutation") -> list:
    """
    Merge enriched fields into genomic criteria based on list indices.

    This function takes a list of genomic criteria (e.g., the mutation_criteria or
    cnv_criteria sublists) and merges in additional fields from the enrichment pass.
    The enrichment objects are expected to reference specific entries by their
    index in the `original` list, allowing multiple entries for the same gene to
    be enriched independently.
    
    Args:
        original: List of genomic criteria dicts to be enriched. Typically a filtered
                  sublist of the full genomic_criteria (e.g., only Mutation or only CNV),
                  where each dict has a "genomic" key.
        enriched: List of enrichment dicts from enrich_mutation_details or enrich_cnv_details.
                  For mutations: [{"index": int, "variant_classification": ..., "exon": ...}, ...]
                  For CNVs: [{"index": int, "cnv_call": ...}, ...]
        enrichment_type: Either "mutation" or "cnv" to determine which fields to merge.
                        - "mutation": merges variant_classification and exon
                        - "cnv": merges cnv_call
        
    Returns:
        The original list with enriched fields merged into matching genomic objects.
        Original list is modified in place and also returned for convenience.
    """
    if not original or not enriched:
        return original
    
    # Build a lookup map from index -> enrichment data.
    # The model is instructed to return "index" fields that correspond to the
    # position in the list that was sent for enrichment (e.g., mutation_criteria).
    enrichment_map = {}
    for item in enriched:
        idx = item.get("index")
        if isinstance(idx, int) and 0 <= idx < len(original):
            enrichment_map[idx] = item
    
    # Merge enriched fields into original criteria using indices
    for i, criterion in enumerate(original):
        enrichment_data = enrichment_map.get(i)
        if not enrichment_data:
            continue

        genomic = criterion.get("genomic", {})
        
        # Merge fields based on enrichment type
        if enrichment_type == "mutation":
            # Merge variant_classification if present and not null
            variant_classification = enrichment_data.get("variant_classification")
            if variant_classification is not None:
                genomic["variant_classification"] = variant_classification
            
            # Merge exon if present and not null
            exon = enrichment_data.get("exon")
            if exon is not None:
                genomic["exon"] = exon
                
        elif enrichment_type == "cnv":
            # Merge cnv_call if present and not null
            cnv_call = enrichment_data.get("cnv_call")
            if cnv_call is not None:
                genomic["cnv_call"] = cnv_call
    
    return original


def safe_get(dict_data, keys):
    for key in keys:
        dict_data = dict_data.get(key, {})
    return dict_data
