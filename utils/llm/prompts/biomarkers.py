"""
Biomarker status prompts: HER2/ER/PR, PD-L1, MMR/MS and disease status, each
with its schema.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.3).
"""

from inspect import cleandoc

import utils.llm.transport as transport


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
