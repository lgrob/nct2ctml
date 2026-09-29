"""
Genomic criteria from eligibility text, for both registries: the gene scan,
the model's inclusion and exclusion criteria, contradiction resolution,
normalisation to CTML genomic nodes, and mutation and CNV detail enrichment.

Moved from src/clinical_trials_gov.py on 2026-09-29 (step 11, phase 2).
"""

from loguru import logger

import src.match_criteria_mapper as mcm
import src.trial_criteria_to_genes as ctg
import utils.ai_helper as ai


def map_ctml_match_genomic_criteria(
    trial_id: str,
    gene_synonym_mapping: dict[str, list[str]],
    inclusion_text: str,
    exclusion_text: str,
):
    """
    Map genomic criteria out of free-text eligibility.

    Source-agnostic: takes the trial's identifier rather than a
    ClinicalTrials.gov document, so CTIS records reach the same gene
    extraction, contradiction resolution and enrichment path.
    """
    nct_id = trial_id
    eligibilityCriteria = inclusion_text + "\n" + exclusion_text
    contains_gene_info = mcm.check_if_eligibility_criteria_contains_gene_info(
        gene_synonym_mapping, eligibilityCriteria
    )  # check if eligibility criteria contains any gene before asking AI

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
            inlcusion_genomic_criteria = ai.get_inclusion_genomic_criteria(
                nct_id, gene_symbols, inclusion_text
            )
            print(f"inlcusion_genomic_criteria: {inlcusion_genomic_criteria}")
            inlcusion_genomic_criteria = _normalize_genomic_criteria(inlcusion_genomic_criteria)
            # Pass 2: Enrichment for detailed mutation/CNV information
            inlcusion_genomic_criteria = _enrich_genomic_criteria(
                nct_id, inlcusion_genomic_criteria, inclusion_text
            )
            print(f"inclusion_genomic_criteria after enrichment: {inlcusion_genomic_criteria}")

        if exclusion_text:
            exclusion_genomic_criteria = ai.get_exclusion_genomic_criteria(
                nct_id, gene_symbols, exclusion_text
            )
            print(f"exclusion_genomic_criteria: {exclusion_genomic_criteria}")
            exclusion_genomic_criteria = _normalize_genomic_criteria(exclusion_genomic_criteria)
            exclusion_genomic_criteria = _enrich_genomic_criteria(
                nct_id, exclusion_genomic_criteria, exclusion_text
            )
            print(f"exclusion_genomic_criteria after enrichment: {exclusion_genomic_criteria}")

        # gene_symbols is passed on so a gene the model returned that the scan
        # did not find is flagged for review (mcm._flag_unsupported_genes).
        genomic_ctml = mcm.convert_to_ctml_genomic_schema(
            inlcusion_genomic_criteria,
            exclusion_genomic_criteria,
            inclusion_text,
            exclusion_text,
            nct_id,
            scanned_genes=gene_symbols,
        )
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
            genomic_criteria = [
                {"genomic": g} for g in genomic_criteria["genomic"] if isinstance(g, dict)
            ]
        else:
            genomic_criteria = [genomic_criteria]

    normalized_criteria = []
    for criterion in genomic_criteria:
        # Handle list items that are already gene-level dicts
        if (
            isinstance(criterion, dict)
            and "genomic" not in criterion
            and ("hugo_symbol" in criterion or "variant_category" in criterion)
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
        logger.info(
            f"NCTID: {nct_id} | Detected mutation details in criteria, enriching {len(mutation_criteria)} mutation(s)"
        )
        enriched_mutations = ai.enrich_mutation_details(nct_id, mutation_criteria, criteria_text)
        if enriched_mutations:
            # Merge into the mutation_criteria list; these are references into genomic_criteria
            ai.merge_enriched_criteria(
                mutation_criteria, enriched_mutations, enrichment_type="mutation"
            )

    # Enrich CNVs if criteria text contains CNV detail keywords
    if cnv_criteria and ai.has_cnv_details(criteria_text):
        logger.info(
            f"NCTID: {nct_id} | Detected CNV details in criteria, enriching {len(cnv_criteria)} CNV(s)"
        )
        enriched_cnvs = ai.enrich_cnv_details(nct_id, cnv_criteria, criteria_text)
        if enriched_cnvs:
            # Merge into the cnv_criteria list; these are references into genomic_criteria
            ai.merge_enriched_criteria(cnv_criteria, enriched_cnvs, enrichment_type="cnv")

    return genomic_criteria
