"""
Mutation and CNV detail enrichment: whether the text has such details at all
(has_mutation_details, has_cnv_details), the prompts that ask for them, and
merging the answers into the genomic criteria, keeping only allowed values.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.3).
"""

import json
import re
from inspect import cleandoc

from loguru import logger

import utils.llm.transport as transport
from utils.genomic_patterns import CNV_DETAIL_KEYWORDS, MUTATION_DETAIL_KEYWORDS

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
        ai_response = transport.send_ai_request(nct_id, prompt, json_schema)
        enrichment_result = transport.parse_ai_response(ai_response, nct_id)

        if isinstance(enrichment_result, dict):
            enriched_mutations = enrichment_result.get("enriched_mutations", [])
        elif isinstance(enrichment_result, list):
            enriched_mutations = enrichment_result
        else:
            logger.warning(
                f"NCTID: {nct_id} | Unexpected enrichment response format: {type(enrichment_result)}"
            )
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
        ai_response = transport.send_ai_request(nct_id, prompt, json_schema)
        enrichment_result = transport.parse_ai_response(ai_response, nct_id)

        if isinstance(enrichment_result, dict):
            enriched_cnvs = enrichment_result.get("enriched_cnvs", [])
        elif isinstance(enrichment_result, list):
            enriched_cnvs = enrichment_result
        else:
            logger.warning(
                f"NCTID: {nct_id} | Unexpected CNV enrichment response format: {type(enrichment_result)}"
            )
            return []

        logger.info(f"NCTID: {nct_id} | CNV enrichment result: {enriched_cnvs}")
        return enriched_cnvs

    except Exception as e:
        logger.error(f"NCTID: {nct_id} | CNV enrichment failed: {e}")
        return []


# Roadmap 6.9: the enrichment prompts had no schema, so the answer was JSON
# found in free text (the 3.1 dry run saw replies that open with prose). The
# allowed values are also enforced in merge_enriched_criteria, because the
# tool call is not strict and a schema enum only guides the model.
VARIANT_CLASSIFICATIONS = (
    "In_Frame_Del",
    "In_Frame_Ins",
    "Splice_Site",
    "Missense_Mutation",
    "Nonsense_Mutation",
    "Frame_Shift_Del",
    "Frame_Shift_Ins",
)


CNV_CALLS = (
    "High Amplification",
    "Low Amplification",
    "Homozygous Deletion",
    "Heterozygous Deletion",
)


MUTATION_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "enriched_mutations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "variant_classification": {"enum": list(VARIANT_CLASSIFICATIONS) + [None]},
                    "exon": {"type": ["integer", "null"]},
                },
                "required": ["index", "variant_classification", "exon"],
            },
        }
    },
    "required": ["enriched_mutations"],
}


CNV_ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "enriched_cnvs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "cnv_call": {"enum": list(CNV_CALLS) + [None]},
                },
                "required": ["index", "cnv_call"],
            },
        }
    },
    "required": ["enriched_cnvs"],
}


def get_mutation_detail_enrichment_prompt(
    genes_with_mutations: list, criteria_text: str, existing_criteria: list
) -> tuple:
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


def get_cnv_detail_enrichment_prompt(
    genes_with_cnv: list, criteria_text: str, existing_criteria: list
) -> tuple:
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


ENRICHMENT_REJECTED: list[
    tuple[str, object]
] = []  # (field, value) the check refused, for measurement


def merge_enriched_criteria(
    original: list, enriched: list, enrichment_type: str = "mutation"
) -> list:
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
                logger.warning(
                    f"enrichment: variant_classification {variant_classification!r} "
                    f"is not an allowed value; not merged"
                )

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
                logger.warning(
                    f"enrichment: cnv_call {cnv_call!r} is not an allowed value; not merged"
                )

    return original
