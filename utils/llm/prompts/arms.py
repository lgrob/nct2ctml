"""
The arm criteria prompt: which eligibility text applies to the whole trial and
which to each arm, with a schema that limits the answer to the trial's own
arm labels (arm_criteria_mapping_schema).

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.3).
"""

import json
from inspect import cleandoc

import utils.llm.schema as llm_schema
import utils.llm.transport as transport


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
