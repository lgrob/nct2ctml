# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

import json
import re
import config
import requests
import urllib.parse
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
    
    schema, prompt = get_ai_prompt_level1_for_original_conditions(original_conditions_list, level1_oncotree_list, nct_id)

    logger.debug(f"NCTID: {nct_id} | AI Prompt for Level 1 diagnosis from original conditions: {prompt}")
        
    ai_response = send_ai_request(nct_id, prompt, schema)
    oncotree_diagnoses_dict = parse_ai_response(ai_response, nct_id)
    return keep_candidates(oncotree_diagnoses_dict, level1_oncotree_list, nct_id, extra=("", "Other"),
                           keep_valid=False)

def get_oncotree_diagnoses_from_trial_info(nct_id: str, trial_info, oncotree_values: set) -> dict:
    schema, prompt = get_ai_prompt_oncotree_diagnoses_from_trial_info(trial_info, list(oncotree_values), nct_id)
    ai_response = send_ai_request(nct_id, prompt, schema)
    return keep_candidates(parse_ai_response(ai_response, nct_id), oncotree_values, nct_id)

def get_child_level_diagnoses_from_condition(nct_id:str, child_nodes_oncotree:set, nct_condition: str) -> dict:
    child_nodes_oncotree_list = list(child_nodes_oncotree)

    schema, prompt = get_ai_prompt_child_values(nct_condition, child_nodes_oncotree_list, nct_id)

    ai_response = send_ai_request(nct_id, prompt, schema)
    oncotree_diagnoses_dict = parse_ai_response(ai_response, nct_id)
    return keep_candidates(oncotree_diagnoses_dict, child_nodes_oncotree_list, nct_id)

def get_her2_er_pr_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_her2_er_pr_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    her2_er_pr_status_dict = parse_ai_response(ai_response, nct_id)   
    return her2_er_pr_status_dict

def get_pdl1_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_pdl1_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    pdl1_status_dict = parse_ai_response(ai_response, nct_id)   
    return pdl1_status_dict

def get_mmr_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_mmr_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    mmr_status_dict = parse_ai_response(ai_response, nct_id)   
    return mmr_status_dict

def get_disease_status(nct_id:str, eligibilityCriteria: str, keywords: list)-> dict:
    schema, prompt = get_disease_status_prompt(eligibilityCriteria, keywords)
    ai_response = send_ai_request(nct_id, prompt, schema)
    disease_status_dict = parse_ai_response(ai_response, nct_id)   
    return disease_status_dict


def get_age_bounds(trial_id: str, inclusion_criteria: str) -> dict:
    """
    Read the enrolment age range out of free-text criteria: both bounds, each
    with its unit and whether it is inclusive.

    CTIS publishes no structured age; ClinicalTrials.gov publishes one whose
    maximum is ambiguous between completed units and an exclusive bound. The
    text is too varied for a pattern ("Age >=1 and <80 years", "Patients aged
    1 to <=21 years", "Children between 1 year (>= 12 months) and 18 years")
    and contains ages that are not eligibility bounds at all, such as the
    Karnofsky/Lansky split at 16 years. The unit is returned as stated rather
    than converted, because the completed-units reading adds one unit of
    whatever the trial wrote. See utils/age_bounds.py for how the answer is
    used.
    """
    schema, prompt = get_age_bounds_prompt(inclusion_criteria)
    ai_response = send_ai_request(trial_id, prompt, schema)
    return parse_ai_response(ai_response, trial_id)


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
    labels = [a.get("label") for a in (arm_groups or []) if isinstance(a, dict) and a.get("label")]
    json_schema = arm_criteria_mapping_schema(labels)
    ai_response = send_ai_request(nct_id, prompt, json_schema)
    mapping = parse_ai_response(ai_response, nct_id)
    return mapping

def get_inclusion_genomic_criteria(nct_id:str, genes:list, eligibilityCriteria:str)-> list:
    json_schema, prompt = get_inclusion_genomic_criteria_prompt(genes, eligibilityCriteria)
    ai_response = send_ai_request(nct_id, prompt, json_schema)
    genomic_criteria = parse_ai_response(ai_response, nct_id)
    return genomic_criteria

def get_exclusion_genomic_criteria(nct_id:str, genes:list, eligibilityCriteria:str)-> list:
    json_schema, prompt = get_exclusion_genomic_criteria_prompt(genes, eligibilityCriteria)
    ai_response = send_ai_request(nct_id, prompt, json_schema)
    genomic_criteria = parse_ai_response(ai_response, nct_id)
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
        enrichment_result = parse_ai_response(ai_response, nct_id)
        
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
        enrichment_result = parse_ai_response(ai_response, nct_id)
        
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

def parse_ai_response(ai_response, trial_id=""):
    return _llm_platform.parse_response(ai_response, trial_id)

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

def prompt_list(values):
    """
    A list printed into a prompt, in a fixed order: sorted, duplicates removed.
    Used for gene lists; diagnosis candidates use diagnosis_prompt_list.

    Every candidate list and gene list reached the prompts in the order of
    the Python set it was built from, and that order follows PYTHONHASHSEED,
    which production does not pin. So one trial got differently ordered
    prompts on every run: a full-pipeline check with a stub model found the
    level-1 and both diagnosis prompts differing under seeds 0/1/2 on 7 of
    8 trials, and with only the gene order changed, 16 of 45 Haiku genomic
    answers changed. Every list printed into a prompt goes through here or
    through diagnosis_prompt_list.
    """
    return sorted({v for v in values if v is not None}, key=str)


def diagnosis_prompt_list(values):
    """
    Diagnosis candidates in a fixed shuffle: ordered by the SHA-256 of each
    name. The result is reproducible and independent of PYTHONHASHSEED.

    The order changes what the model answers, so it was measured: Haiku 4.5,
    the 50-trial diagnosis benchmark, 3 runs per order.

    | order | population recall | population precision | diagnoses |
    |---|---|---|---|
    | set order, seeds 0/1/2 | 0.934 / 0.937 / 0.938 | 0.784 / 0.810 / 0.796 | 343 / 309 / 325 |
    | alphabetical | 0.925 | 0.816 | 292 |
    | Oncotree tree order | 0.915 | 0.784 | 287 |
    | SHA-256 shuffle | 0.942 | 0.798 | 312 |

    Alphabetical and tree order lose recall. Both put related names next to
    each other; that the model then stops early inside a group is a guess,
    not measured. The shuffle
    behaves like the random orders every earlier measurement used, and it
    is no worse than them: recall +0.007 [-0.009, +0.031] paired per trial.
    Each name's position depends only on the name, so adding an Oncotree
    node does not reorder the rest.
    """
    import hashlib
    return sorted({v for v in values if v is not None},
                  key=lambda v: (hashlib.sha256(str(v).encode("utf-8")).hexdigest(), str(v)))


def get_ai_prompt_level1_for_original_conditions(original_conditions_list, level1_oncotree_list, trial_id=""):
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    level1_oncotree_list = diagnosis_prompt_list(level1_oncotree_list)
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
    return level1_diagnoses_schema(level1_oncotree_list, trial_id), cleandoc(prompt)

def get_ai_prompt_oncotree_diagnoses_from_trial_info(trial_info, oncotree_values, trial_id=""):
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    oncotree_values = diagnosis_prompt_list(oncotree_values)
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

    return oncotree_diagnoses_schema(oncotree_values, trial_id), cleandoc(prompt)

def get_ai_prompt_child_values(nct_condition, child_nodes_oncotree_list, trial_id=""):
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    child_nodes_oncotree_list = diagnosis_prompt_list(child_nodes_oncotree_list)

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
    return child_values_schema(child_nodes_oncotree_list, trial_id), cleandoc(prompt)

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


def get_age_bounds_prompt(inclusion_criteria):
    prompt = f"""Task: From the InclusionCriteria, find the age range a participant must be in to enrol.

        InclusionCriteria: {inclusion_criteria}

        Rules:
        - Report only limits on the participant's age at enrolment.
        - Ignore ages that are not eligibility limits: the age at which a
          different performance scale applies (Karnofsky vs Lansky), the age at
          original diagnosis when it differs from enrolment age, and ages in
          dosing, consent or assent text.
        - If different cohorts, parts or phases allow different ages, report the
          widest range across them: the lowest minimum and the highest maximum.
          Any one cohort admitting the participant is enough.
        - Report each number and unit exactly as written. Do not convert
          "18 months" to years.
        - inclusive is true when the limit itself is allowed: ">=", "at least",
          "or older", "<=", "or younger", "up to and including", and ranges such
          as "between 1 and 21 years" or "1-21 years". inclusive is false when
          the limit itself is excluded: "<", "under", "younger than", "less
          than", "older than", "before their 22nd birthday".
        - If no minimum (or no maximum) is stated, set its value to null.

        Output in JSON format:
        {{
        "minimum": {{"value": 1, "unit": "years", "inclusive": true}},
        "maximum": {{"value": null, "unit": "years", "inclusive": true}}
        }}
        where value is a number or null, and unit is one of years, months,
        weeks, days.
        """
    return AGE_BOUNDS_SCHEMA, cleandoc(prompt)


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
# schema restricts it too, which on a grammar-compiling backend makes an
# off-list answer impossible to emit rather than merely discouraged.
# "Lymphoma" is not an Oncotree display name and cannot be produced there.
# On Anthropic the tool call is not `strict`, so the enum is guidance: the
# cached Haiku answers to the 50-trial benchmark contain "Lymphoma" once per
# replicate (NCT02332668, 1 of 440 and 1 of 426 answers) under a 283-value
# enum. That one is caught - filter_diagnoses drops terms that are not
# Oncotree names when the CTML is built - but an Oncotree name from outside
# the candidate branch would pass. MatchMiner's _SOLID_ and
# _LIQUID_ wildcards are deliberately absent too: the pipeline derives those
# from the trial's conditions, and a model should not be invited to guess them.

# Self-hosted backends compile the schema into a generation grammar, and one
# with several hundred alternatives is slow to build. Above the cap the enum is
# dropped and the schema still guarantees well-formed JSON of the right shape.
# The cap depends on the backend - config.SCHEMA_ENUM_MAX_VALUES says why - and
# this is the fallback for a platform it does not list.
_DEFAULT_MAX_ENUM_VALUES = 400

# How often a candidate list was sent as an enum ("enum"), came near the cap
# ("near_cap") or was sent without its enum ("dropped"), for the run summary.
# Module state because the schema builders are plain functions called from
# deep inside the mapping path; reset_enum_cap_events() starts a new count.
ENUM_CAP_EVENTS = {"enum": 0, "near_cap": 0, "dropped": 0, "largest": 0}


def max_enum_values():
    """The enum cap for config.LLM_PLATFORM; None means the enum is never dropped."""
    caps = getattr(config, "SCHEMA_ENUM_MAX_VALUES", {}) or {}
    platform = str(getattr(config, "LLM_PLATFORM", "")).lower()
    return caps.get(platform, _DEFAULT_MAX_ENUM_VALUES)


def reset_enum_cap_events():
    for k in ENUM_CAP_EVENTS:
        ENUM_CAP_EVENTS[k] = 0
    for k in OFF_LIST_EVENTS:
        OFF_LIST_EVENTS[k] = 0


# Answers checked against, and dropped from, their call's candidate list;
# see keep_candidates.
OFF_LIST_EVENTS = {"checked": 0, "recased": 0, "kept_for_review": 0, "dropped": 0}
# trial id -> Oncotree names answered off-list; read and cleared by
# TrialMapManager, which records them as diagnosis_off_list and routes the
# trial to review.
OFF_LIST_BY_TRIAL = {}


def keep_candidates(result, allowed, trial_id="", extra=(), keep_valid=True):
    """
    A result that is not an object with an oncotree_diagnoses list (a
    malformed answer, or {} from text that did not parse) becomes
    {"oncotree_diagnoses": []}: no diagnosis from this call, rather than an
    exception downstream that loses the trial (full run 2026-09-25).

    Keep only diagnosis answers that were on the call's candidate list.

    The enum in the schema is what makes an off-list answer impossible on a
    grammar-compiling backend. On Anthropic the forced tool call is not
    `strict`, so the enum only guides the model, and an off-list answer
    reaches the pipeline. filter_diagnoses later drops a term that is not an
    Oncotree name ("Lymphoma", once per replicate on NCT02332668). But an
    Oncotree name from outside the branch the call offered passes it, and
    that is the wrong-branch error the candidate list exists to prevent. So
    the check is repeated here, in code, against exactly the list that was
    sent, whatever the backend.

    What happens to an off-list answer:
    - **Differs only in letter case:** rewritten to the candidate.
    - **Not an Oncotree name:** dropped.
    - **Valid Oncotree name from outside the offered list:** kept, recorded in
      OFF_LIST_BY_TRIAL, and the trial goes to review. Replaying the saved
      Haiku and Sonnet stage-2 runs (2,585 answers) found 4 off-list
      answers. Three were "Lymphoma", which is not an Oncotree name. The one
      Oncotree name was "Neuroblastoma" on NCT03838042, which the text
      lists and the answer key holds; stage 1 had failed to offer its
      branch. Dropping such answers would remove correct diagnoses; review
      lets a curator decide.
    - **Level-1 calls (keep_valid=False):** an off-list answer is dropped even
      if it is a valid name, because the caller uses the answer as a branch
      key.

    Items are strings, or {"oncotree_value": ...} objects for the level-1
    schema. `extra` holds the values that schema also permits ("", "Other").
    """
    if not isinstance(result, dict) or not isinstance(result.get("oncotree_diagnoses"), list):
        # Callers index ["oncotree_diagnoses"] directly (the level-1 caller
        # does), so a malformed or empty answer must still have the key.
        return {**(result if isinstance(result, dict) else {}), "oncotree_diagnoses": []}
    permitted = {a for a in list(allowed) + list(extra) if a is not None}
    by_case = {}
    for a in permitted:
        by_case.setdefault(str(a).casefold(), []).append(a)
    kept = []
    for item in result["oncotree_diagnoses"]:
        value = item.get("oncotree_value") if isinstance(item, dict) else item
        OFF_LIST_EVENTS["checked"] += 1
        if value in permitted:
            kept.append(item)
            continue
        same = by_case.get(str(value).casefold(), []) if isinstance(value, str) else []
        if len(same) == 1:
            OFF_LIST_EVENTS["recased"] += 1
            logger.info(f"{trial_id} | diagnosis answer {value!r} recased to candidate {same[0]!r}")
            kept.append(dict(item, oncotree_value=same[0]) if isinstance(item, dict) else same[0])
            continue
        from utils.reference_validation import canonical_diagnosis
        name = canonical_diagnosis(value) if keep_valid and isinstance(value, str) else None
        if name:
            OFF_LIST_EVENTS["kept_for_review"] += 1
            OFF_LIST_BY_TRIAL.setdefault(trial_id, set()).add(name)
            logger.warning(f"{trial_id} | diagnosis answer {value!r} was not among the "
                           f"{len(permitted)} candidates offered; kept, trial goes to review")
            kept.append(item)
            continue
        OFF_LIST_EVENTS["dropped"] += 1
        logger.warning(f"{trial_id} | diagnosis answer {value!r} was not among the "
                       f"{len(permitted)} candidates offered; dropped")
    return dict(result, oncotree_diagnoses=kept)


def enum_cap_summary() -> str:
    e = ENUM_CAP_EVENTS
    return (f"Schema enums: {e['enum']} sent, {e['near_cap']} near the cap, "
            f"{e['dropped']} dropped over the cap ({max_enum_values()} on "
            f"{getattr(config, 'LLM_PLATFORM', '?')}); largest list {e['largest']}. "
            f"Diagnosis answers: {OFF_LIST_EVENTS['checked']} checked against their "
            f"candidate list, {OFF_LIST_EVENTS['recased']} recased, "
            f"{OFF_LIST_EVENTS['kept_for_review']} off-list kept for review, "
            f"{OFF_LIST_EVENTS['dropped']} dropped")


def _one_of(allowed, extra=(), trial_id=""):
    """
    A string constrained to `allowed`, or an unconstrained one if too many.

    Dropping the enum used to be silent, and it is exactly the failure the
    enum exists to prevent: an off-list diagnosis becomes sayable again. It
    now logs a WARNING with the trial and size, and an INFO above
    config.SCHEMA_ENUM_NEAR_CAP_FRACTION of the cap. Measured 2026-09-24 on
    the two Haiku replicates of the 50-trial benchmark: the largest list sent
    was 370 (NCT02813135), p95 226, 2-3 calls above 320 and none above 400;
    across the 1,255 cached trials the seed floor alone reaches 438.
    """
    values = sorted({a for a in list(allowed) + list(extra) if a is not None})
    if not values:
        # An empty enum would make every answer invalid.
        return {"type": "string"}
    n = len(values)
    ENUM_CAP_EVENTS["largest"] = max(ENUM_CAP_EVENTS["largest"], n)
    cap = max_enum_values()
    if cap is not None and n > cap:
        ENUM_CAP_EVENTS["dropped"] += 1
        logger.warning(f"{trial_id} | {n} candidates exceed the schema enum cap of {cap} "
                       f"on {config.LLM_PLATFORM}; enum dropped, off-list answers are "
                       f"possible for this call")
        return {"type": "string"}
    ENUM_CAP_EVENTS["enum"] += 1
    near = getattr(config, "SCHEMA_ENUM_NEAR_CAP_FRACTION", 0.8)
    if cap is not None and n > near * cap:
        ENUM_CAP_EVENTS["near_cap"] += 1
        logger.info(f"{trial_id} | {n} candidates, near the schema enum cap of {cap}")
    return {"type": "string", "enum": values}


def oncotree_diagnoses_schema(allowed, trial_id=""):
    return {
        "type": "object",
        "properties": {"oncotree_diagnoses": {"type": "array",
                                              "items": _one_of(allowed, trial_id=trial_id)}},
        "required": ["oncotree_diagnoses"],
    }


def level1_diagnoses_schema(allowed, trial_id=""):
    # "" and "Other" are how the caller is told a condition has no level_1, and
    # clinical_trials_gov skips exactly those two. They must stay sayable, or a
    # constrained model is forced to pick a branch it does not believe in.
    return {
        "type": "object",
        "properties": {"oncotree_diagnoses": {"type": "array", "items": {
            "type": "object",
            "properties": {"cancer_condition": {"type": "string"},
                           "oncotree_value": _one_of(allowed, ("", "Other"), trial_id)},
            "required": ["cancer_condition", "oncotree_value"],
        }}},
        "required": ["oncotree_diagnoses"],
    }


def child_values_schema(allowed, trial_id=""):
    return {
        "type": "object",
        "properties": {"cancer_condition": {"type": "string"},
                       "oncotree_diagnoses": {"type": "array",
                                              "items": _one_of(allowed, trial_id=trial_id)}},
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

def arm_criteria_mapping_schema(arm_labels):
    """
    Constrain the global-vs-per-arm split.

    This was the last prompt asking a model for JSON without a grammar, and it
    is the one that emits the largest nested object. It produced invalid JSON
    on the cluster - a parse failure at character 6057, well under the output
    cap, so malformed rather than truncated - and NCT05745714 lost its entire
    genomic block as a result, silently, because parse_response returns {}.

    arm_label is an enum over the labels actually present, which also enforces
    in the grammar what the prompt only asks for in prose: that the label come
    back verbatim so it can be mapped to a CTML arm afterwards.
    """
    text = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "global": {
                "type": "object",
                "properties": {"inclusion_text": text, "exclusion_text": text},
                "required": ["inclusion_text", "exclusion_text"],
            },
            "arms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "arm_label": _one_of(arm_labels),
                        "inclusion_text": text,
                        "exclusion_text": text,
                    },
                    "required": ["arm_label", "inclusion_text", "exclusion_text"],
                },
            },
        },
        "required": ["global", "arms"],
    }


DISEASE_STATUS_SCHEMA = {
    "type": "object",
    "properties": {"disease_status": {"type": "array", "items": {
        "type": "string", "enum": [
            "Untreated", "Localized", "Locally Advanced", "Metastatic",
            "Advanced", "Recurrent", "Refractory", "Unresectable", "Early Stage"]}}},
    "required": ["disease_status"],
}

# Roadmap 6.9: the enrichment prompts had no schema, so the answer was JSON
# found in free text (the 3.1 dry run saw replies that open with prose). The
# allowed values are also enforced in merge_enriched_criteria, because the
# tool call is not strict and a schema enum only guides the model.
VARIANT_CLASSIFICATIONS = ("In_Frame_Del", "In_Frame_Ins", "Splice_Site", "Missense_Mutation",
                           "Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins")
CNV_CALLS = ("High Amplification", "Low Amplification", "Homozygous Deletion", "Heterozygous Deletion")

MUTATION_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {"enriched_mutations": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "variant_classification": {"enum": list(VARIANT_CLASSIFICATIONS) + [None]},
            "exon": {"type": ["integer", "null"]},
        },
        "required": ["index", "variant_classification", "exon"],
    }}},
    "required": ["enriched_mutations"],
}

CNV_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {"enriched_cnvs": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "cnv_call": {"enum": list(CNV_CALLS) + [None]},
        },
        "required": ["index", "cnv_call"],
    }}},
    "required": ["enriched_cnvs"],
}

_AGE_BOUND_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": ["number", "null"]},
        "unit": {"type": "string", "enum": ["years", "months", "weeks", "days"]},
        "inclusive": {"type": "boolean"},
    },
    "required": ["value", "unit", "inclusive"],
}

AGE_BOUNDS_SCHEMA = {
    "type": "object",
    "properties": {"minimum": _AGE_BOUND_SCHEMA, "maximum": _AGE_BOUND_SCHEMA},
    "required": ["minimum", "maximum"],
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
                    # The other gene of a named fusion (EWSR1::FLI1 -> FLI1).
                    # Absent means any fusion of hugo_symbol qualifies.
                    "fusion_partner": {"type": "string"},
                    # Kept from utils/schema.py's trial_genomic_json_schema,
                    # which declared these and was never wired to anything.
                    # Omitting them here silently removed the model's ability
                    # to say them: llama.cpp builds its grammar from the
                    # declared properties, so an undeclared field cannot be
                    # generated. ctml/reviewed uses variant_classification on
                    # three trials and exon on one.
                    "variant_classification": {
                        "type": "string",
                        "enum": [
                            "In_Frame_Del", "In_Frame_Ins", "Splice_Site",
                            "Missense_Mutation", "Nonsense_Mutation",
                            "Frame_Shift_Del", "Frame_Shift_Ins",
                        ],
                    },
                    "exon": {"type": "integer"},
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
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    genes = prompt_list(genes)
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
    9. When the criteria name a specific fusion by BOTH genes (e.g. "EWSR1-FLI1", "BCR::ABL1", "KMT2A rearranged with AFF1"), return ONE "Structural Variation" entry with the first-named gene in "hugo_symbol" and the other in "fusion_partner". When only one gene is named ("NTRK1 rearrangement", "any KMT2A fusion"), omit "fusion_partner". Do not derive genes from cytogenetic notation such as t(9;22) unless the genes are also written.
    
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
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    genes = prompt_list(genes)
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
    return MUTATION_ENRICHMENT_SCHEMA, cleandoc(prompt)


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
    return CNV_ENRICHMENT_SCHEMA, cleandoc(prompt)


ENRICHMENT_REJECTED = []   # (field, value) the check refused, for measurement


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
            # Only values from the allowed lists are merged (roadmap 6.9): the
            # schema enum is advisory on a non-strict tool call.
            variant_classification = enrichment_data.get("variant_classification")
            if variant_classification in VARIANT_CLASSIFICATIONS:
                genomic["variant_classification"] = variant_classification
            elif variant_classification is not None:
                ENRICHMENT_REJECTED.append(("variant_classification", variant_classification))
                logger.warning(f"enrichment: variant_classification {variant_classification!r} "
                               f"is not an allowed value; not merged")

            # Merge exon if it is a positive whole number
            exon = enrichment_data.get("exon")
            if isinstance(exon, int) and not isinstance(exon, bool) and exon > 0:
                genomic["exon"] = exon
            elif exon is not None:
                ENRICHMENT_REJECTED.append(("exon", exon))
                logger.warning(f"enrichment: exon {exon!r} is not a positive integer; not merged")
                
        elif enrichment_type == "cnv":
            # Merge cnv_call if present and not null
            cnv_call = enrichment_data.get("cnv_call")
            if cnv_call in CNV_CALLS:
                genomic["cnv_call"] = cnv_call
            elif cnv_call is not None:
                ENRICHMENT_REJECTED.append(("cnv_call", cnv_call))
                logger.warning(f"enrichment: cnv_call {cnv_call!r} is not an allowed value; not merged")
    
    return original


def safe_get(dict_data, keys):
    for key in keys:
        dict_data = dict_data.get(key, {})
    return dict_data
