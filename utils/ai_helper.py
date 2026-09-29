# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

import json
from inspect import cleandoc

from loguru import logger

import config
import utils.llm.schema as llm_schema
import utils.llm.transport as transport


def get_level1_diagnosis_from_original_conditions(
    nct_id: str, original_conditions: dict, level1_oncotree: set
) -> dict:
    original_conditions_list = list(original_conditions)
    level1_oncotree_list = list(level1_oncotree)

    schema, prompt = get_ai_prompt_level1_for_original_conditions(
        original_conditions_list, level1_oncotree_list, nct_id
    )

    logger.debug(
        f"NCTID: {nct_id} | AI Prompt for Level 1 diagnosis from original conditions: {prompt}"
    )

    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    oncotree_diagnoses_dict = transport.parse_ai_response(ai_response, nct_id)
    return llm_schema.keep_candidates(
        oncotree_diagnoses_dict, level1_oncotree_list, nct_id, extra=("", "Other"), keep_valid=False
    )


def get_oncotree_diagnoses_from_trial_info(nct_id: str, trial_info, oncotree_values: set) -> dict:
    schema, prompt = get_ai_prompt_oncotree_diagnoses_from_trial_info(
        trial_info, list(oncotree_values), nct_id
    )
    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    return llm_schema.keep_candidates(
        transport.parse_ai_response(ai_response, nct_id), oncotree_values, nct_id
    )


def get_child_level_diagnoses_from_condition(
    nct_id: str, child_nodes_oncotree: set, nct_condition: str
) -> dict:
    child_nodes_oncotree_list = list(child_nodes_oncotree)

    schema, prompt = get_ai_prompt_child_values(nct_condition, child_nodes_oncotree_list, nct_id)

    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    oncotree_diagnoses_dict = transport.parse_ai_response(ai_response, nct_id)
    return llm_schema.keep_candidates(oncotree_diagnoses_dict, child_nodes_oncotree_list, nct_id)


def get_her2_er_pr_status(nct_id: str, eligibilityCriteria: str, keywords: list) -> dict:
    schema, prompt = get_her2_er_pr_status_prompt(eligibilityCriteria, keywords)
    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    her2_er_pr_status_dict = transport.parse_ai_response(ai_response, nct_id)
    return her2_er_pr_status_dict


def get_pdl1_status(nct_id: str, eligibilityCriteria: str, keywords: list) -> dict:
    schema, prompt = get_pdl1_status_prompt(eligibilityCriteria, keywords)
    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    pdl1_status_dict = transport.parse_ai_response(ai_response, nct_id)
    return pdl1_status_dict


def get_mmr_status(nct_id: str, eligibilityCriteria: str, keywords: list) -> dict:
    schema, prompt = get_mmr_status_prompt(eligibilityCriteria, keywords)
    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    mmr_status_dict = transport.parse_ai_response(ai_response, nct_id)
    return mmr_status_dict


def get_disease_status(nct_id: str, eligibilityCriteria: str, keywords: list) -> dict:
    schema, prompt = get_disease_status_prompt(eligibilityCriteria, keywords)
    ai_response = transport.send_ai_request(nct_id, prompt, schema)
    disease_status_dict = transport.parse_ai_response(ai_response, nct_id)
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
    ai_response = transport.send_ai_request(trial_id, prompt, schema)
    return transport.parse_ai_response(ai_response, trial_id)


def get_arm_criteria_mapping(
    nct_id: str, arm_groups: list, inclusion_criteria: str, exclusion_criteria: str
) -> dict:
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
    ai_response = transport.send_ai_request(nct_id, prompt, json_schema)
    mapping = transport.parse_ai_response(ai_response, nct_id)
    return mapping


def get_ai_prompt_level1_for_original_conditions(
    original_conditions_list, level1_oncotree_list, trial_id=""
):
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    level1_oncotree_list = llm_schema.diagnosis_prompt_list(level1_oncotree_list)
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
    oncotree_values = llm_schema.diagnosis_prompt_list(oncotree_values)

    # Roadmap 2.8: only in "labelled" mode, so legacy prompts stay byte-identical.
    exclusion_rule = (
        "\n        - Conditions named under Exclusion Criteria are excluded from the trial: do not "
        "return them, unless the Inclusion Criteria (or the Title or Conditions) also name them."
        if getattr(config, "DIAGNOSIS_INPUT", "legacy") == "labelled"
        else ""
    )
    prompt = f"""Task: From the TrialInfo, extract OncotreeValues that correspond to medical conditions explicitly mentioned in the text.
        Rules:
        - Only include a diagnosis if the condition or cancer type is explicitly stated in TrialInfo.
        - Do not infer diagnoses from drug names, treatment regimens, parent studies, or other indirect clues.
        - If no condition or cancer type is explicitly mentioned, return an empty list.
        - Choose only from the provided OncotreeValues.{exclusion_rule}

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
    child_nodes_oncotree_list = llm_schema.diagnosis_prompt_list(child_nodes_oncotree_list)

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


def get_arm_criteria_mapping_prompt(
    arm_groups: list, inclusion_criteria: str, exclusion_criteria: str
) -> str:
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


def oncotree_diagnoses_schema(allowed, trial_id=""):
    return {
        "type": "object",
        "properties": {
            "oncotree_diagnoses": {
                "type": "array",
                "items": llm_schema._one_of(allowed, trial_id=trial_id),
            }
        },
        "required": ["oncotree_diagnoses"],
    }


def level1_diagnoses_schema(allowed, trial_id=""):
    # "" and "Other" are how the caller is told a condition has no level_1, and
    # clinical_trials_gov skips exactly those two. They must stay sayable, or a
    # constrained model is forced to pick a branch it does not believe in.
    return {
        "type": "object",
        "properties": {
            "oncotree_diagnoses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cancer_condition": {"type": "string"},
                        "oncotree_value": llm_schema._one_of(allowed, ("", "Other"), trial_id),
                    },
                    "required": ["cancer_condition", "oncotree_value"],
                },
            }
        },
        "required": ["oncotree_diagnoses"],
    }


def child_values_schema(allowed, trial_id=""):
    return {
        "type": "object",
        "properties": {
            "cancer_condition": {"type": "string"},
            "oncotree_diagnoses": {
                "type": "array",
                "items": llm_schema._one_of(allowed, trial_id=trial_id),
            },
        },
        "required": ["oncotree_diagnoses"],
    }


_RECEPTOR_VALUES = ["Positive", "Negative", "Unknown", "!Positive", "!Negative"]
HER2_ER_PR_SCHEMA = {
    "type": "object",
    "properties": {
        name: {"type": "string", "enum": _RECEPTOR_VALUES}
        for name in ("her2_status", "er_status", "pr_status")
    },
    "required": ["her2_status", "er_status", "pr_status"],
}

PDL1_SCHEMA = {
    "type": "object",
    "properties": {"pdl1_status": {"type": "string", "enum": ["High", "Low", "Unknown"]}},
    "required": ["pdl1_status"],
}

# No "Unknown" here, so neither field is required: forcing a choice between
# proficient and deficient would invent one.
MMR_MS_SCHEMA = {
    "type": "object",
    "properties": {
        "mmr_status": {
            "type": "string",
            "enum": ["MMR-Proficient", "MMR-Deficient", "!MMR-Proficient", "!MMR-Deficient"],
        },
        "ms_status": {"type": "string", "enum": ["MSI-H", "MSI-L", "MSS", "!MSI-H", "!MSI-L"]},
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
                        "arm_label": llm_schema._one_of(arm_labels),
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
    "properties": {
        "disease_status": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "Untreated",
                    "Localized",
                    "Locally Advanced",
                    "Metastatic",
                    "Advanced",
                    "Recurrent",
                    "Refractory",
                    "Unresectable",
                    "Early Stage",
                ],
            },
        }
    },
    "required": ["disease_status"],
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


def safe_get(dict_data, keys):
    for key in keys:
        dict_data = dict_data.get(key, {})
    return dict_data
