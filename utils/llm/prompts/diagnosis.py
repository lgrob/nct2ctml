"""
The diagnosis prompts: level-1 Oncotree nodes from the conditions or the
eligibility text, then the children within them, each with its schema
limited to the candidate list.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.3).
"""

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
