"""
The genomic criteria prompts: inclusion (in the variants baseline, rules,
roles and roles_union, per config.GENOMIC_PROMPT) and exclusion, their
schemas, and the roles that decide which genes enter the match tree.
Genes kept out are recorded per trial in ROLE_DROPS.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.3).
"""

from inspect import cleandoc

import config
import utils.llm.schema as llm_schema
import utils.llm.transport as transport

# Roadmap 2.9, "roles": genes the model classified as something other than an
# entry requirement, per trial id: [(gene, role)]. Read by the mapper, which
# records them as gene_role_dropped on the trial.
ROLE_DROPS = {}


def get_inclusion_genomic_criteria(nct_id: str, genes: list, eligibilityCriteria: str) -> list:
    json_schema, prompt = get_inclusion_genomic_criteria_prompt(genes, eligibilityCriteria)
    ai_response = transport.send_ai_request(nct_id, prompt, json_schema)
    genomic_criteria = transport.parse_ai_response(ai_response, nct_id)
    if getattr(config, "GENOMIC_PROMPT", "baseline") in ("roles", "roles_union") and isinstance(
        genomic_criteria, list
    ):
        kept = []
        for c in genomic_criteria:
            g = c.get("genomic") if isinstance(c, dict) else None
            role = str(g.pop("role", "requirement")) if isinstance(g, dict) else "requirement"
            if role in _KEPT_ROLES:
                kept.append(c)
            elif isinstance(g, dict) and g.get("hugo_symbol"):
                ROLE_DROPS.setdefault(nct_id, []).append((str(g["hugo_symbol"]), role))
        genomic_criteria = kept
    return genomic_criteria


def get_exclusion_genomic_criteria(nct_id: str, genes: list, eligibilityCriteria: str) -> list:
    json_schema, prompt = get_exclusion_genomic_criteria_prompt(genes, eligibilityCriteria)
    ai_response = transport.send_ai_request(nct_id, prompt, json_schema)
    genomic_criteria = transport.parse_ai_response(ai_response, nct_id)
    return genomic_criteria


GENOMIC_ROLES = [
    "requirement",
    "risk_group",
    "cohort_specific",
    "conditional",
    "alternative_route",
    "example",
    "expression_or_germline",
]


# "roles_union" (roadmap 2.9b) adds cohort_union: a gene one cohort needs in a
# trial where EVERY cohort needs one of the returned genes. Kept in the tree
# like a requirement, so a strata trial (ALK / MET / ROS1) keeps its genetics.
GENOMIC_ROLES_UNION = GENOMIC_ROLES + ["cohort_union"]


_KEPT_ROLES = {"requirement", "cohort_union"}


def _with_role(schema, roles=GENOMIC_ROLES):
    import copy

    s = copy.deepcopy(schema)
    g = s["items"]["properties"]["genomic"]
    g["properties"]["role"] = {"type": "string", "enum": roles}
    g["required"] = g["required"] + ["role"]
    return s


# a lot of trial criteria mention exclusion too in inclusion criteria hence the prompt supplies both inclusion and exclusion instructions
# Shape that _enrich_genomic_criteria expects. Supplied to Ollama as
# "format", which constrains decoding rather than merely asking for JSON.
# Without it a model will happily echo the prompt's own input labels back as
# keys - gemma3:27b returned {"EligibilityCriteria": ..., "Possible GeneList":
# [], "Output": []} on 8 of 12 benchmark trials, treating the prompt as a
# template to fill in.
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
                            "Mutation",
                            "Copy Number Variation",
                            "Structural Variation",
                            "Any Variation",
                            "!Mutation",
                            "!Copy Number Variation",
                            "!Structural Variation",
                            "!Any Variation",
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
                            "In_Frame_Del",
                            "In_Frame_Ins",
                            "Splice_Site",
                            "Missense_Mutation",
                            "Nonsense_Mutation",
                            "Frame_Shift_Del",
                            "Frame_Shift_Ins",
                        ],
                    },
                    "exon": {"type": "integer"},
                    "cnv_call": {
                        "type": "string",
                        "enum": [
                            "Low Amplification",
                            "High Amplification",
                            "Homozygous Deletion",
                            "Heterozygous Deletion",
                            "!Low Amplification",
                            "!High Amplification",
                            "!Homozygous Deletion",
                            "!Heterozygous Deletion",
                        ],
                    },
                },
                "required": ["hugo_symbol", "variant_category"],
            }
        },
        "required": ["genomic"],
    },
}


GENOMIC_ROLE_SCHEMA = _with_role(GENOMIC_CRITERIA_SCHEMA)


GENOMIC_ROLE_UNION_SCHEMA = _with_role(GENOMIC_CRITERIA_SCHEMA, GENOMIC_ROLES_UNION)


_EXAMPLE_ANCHOR = "    Example 1:"


_NOT_A_REQUIREMENT = """(a) it defines a risk group, a stratification or a treatment allocation among patients who can all enter;
       (b) it is required only for some cohorts, parts, strata, phases or arms, while others enter without it;
       (c) it is required only under a condition not every patient meets ("if a biopsy is done, H3 K27M must be confirmed");
       (d) it is one route to entry among routes that are not genetic ("high-risk AML defined by a TP53 mutation, a complex karyotype or therapy-related disease");
       (e) it is only an example inside a broader criterion ("an actionable alteration such as ALK or ROS1" when any actionable alteration qualifies);
       (f) the text is about protein expression (IHC, flow cytometry) or a germline syndrome (neurofibromatosis type 1)."""


_RULES_TEXT = (
    """    10. ENTRY REQUIREMENTS ONLY. Return a gene only if EVERY patient entering (the trial, or the arm this text describes) must carry the alteration,
       alone or as one alternative in a list made only of genetic alterations. Do NOT return a gene when:
       """
    + _NOT_A_REQUIREMENT
    + """
       If no gene is an entry requirement for every patient, return an empty list [].
       Example: "Part A: any relapsed solid tumour. Part B: solid tumours with a CTNNB1 or APC mutation." -> []
"""
)


_ROLES_TEXT = (
    """    10. For EVERY gene you return, set "role" to exactly one of:
       "requirement" - EVERY patient entering (the trial, or the arm this text describes) must carry the alteration, alone or as one
                       alternative in a list made only of genetic alterations;
       "risk_group" (a), "cohort_specific" (b), "conditional" (c), "alternative_route" (d), "example" (e), "expression_or_germline" (f), where:
       """
    + _NOT_A_REQUIREMENT
    + """
       Only "requirement" genes decide eligibility; the other roles are kept for a curator. When unsure, prefer the narrower role over "requirement".
       Example: "Part A: any relapsed solid tumour. Part B: solid tumours with a CTNNB1 or APC mutation." ->
       CTNNB1 and APC, both "role": "cohort_specific".
"""
)


_ROLES_UNION_TEXT = _ROLES_TEXT.replace(
    """       Only "requirement" genes decide eligibility;""",
    """       "cohort_union" - the gene is needed only by some cohorts, parts or strata, BUT every cohort of the trial needs one of the
                       genes you return (no cohort enters without a genetic alteration). Use it for every gene of such a trial.
       Example: "Stratum 1: ALK fusion. Stratum 2: MET amplification. Stratum 3: ROS1 fusion." -> ALK, MET, ROS1, all "cohort_union".
       Only "requirement" and "cohort_union" genes decide eligibility;""",
)
assert _ROLES_UNION_TEXT != _ROLES_TEXT


def get_inclusion_genomic_criteria_prompt(genes, inclusion_criteria):
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    genes = llm_schema.prompt_list(genes)
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
    variant = getattr(config, "GENOMIC_PROMPT", "baseline")
    if variant in ("rules", "roles", "roles_union"):
        assert prompt.count(_EXAMPLE_ANCHOR) == 1
        text = {"rules": _RULES_TEXT, "roles": _ROLES_TEXT, "roles_union": _ROLES_UNION_TEXT}[
            variant
        ]
        prompt = prompt.replace(_EXAMPLE_ANCHOR, text + _EXAMPLE_ANCHOR, 1)
        schema = {
            "rules": GENOMIC_CRITERIA_SCHEMA,
            "roles": GENOMIC_ROLE_SCHEMA,
            "roles_union": GENOMIC_ROLE_UNION_SCHEMA,
        }[variant]
        return schema, cleandoc(prompt)
    return GENOMIC_CRITERIA_SCHEMA, cleandoc(prompt)


def get_exclusion_genomic_criteria_prompt(genes, exclusion_criteria):
    # Sorted so the prompt text does not depend on set order (PYTHONHASHSEED);
    # see prompt_list(). Roadmap 1.9.
    genes = llm_schema.prompt_list(genes)
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
