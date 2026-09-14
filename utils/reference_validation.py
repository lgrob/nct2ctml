"""
Validate model-proposed Oncotree diagnoses and HUGO symbols against the
reference files, and drop what does not exist.

Both genomic and diagnosis prompts hand the model the permitted vocabulary,
so every value it returns should already be drawn from these files. It is not:
benchmark runs produced `_SOLID_` and `Leukemia` as Oncotree diagnoses, `AML`
(an Oncotree *code*) where the display name belongs, and `H3` as a gene symbol
alongside the three real histone genes. None of these match a patient - CTML
matching is on exact strings - so they are silent false negatives rather than
visible errors, which is what makes them worth catching mechanically.

This runs after the LLM, deterministically, and needs no second opinion:
either a string is in the reference or it is not. Checked against the 17
hand-curated trials in ctml/reviewed, it drops nothing that a human kept.

Codes are accepted and rewritten to their display name. The two namespaces do
not overlap - no Oncotree code is also some other node's display name - so the
rewrite is unambiguous. Case-insensitive rescue is likewise safe: no two
Oncotree display names differ only by case.
"""
import csv
import re
from functools import lru_cache

from loguru import logger

import config

# "Acute Myeloid Leukemia (AML)" -> name, code. Codes are upper-case with
# digits and a few separators; anything else is a name containing brackets.
_LEVEL_VALUE = re.compile(r"^(.*)\s+\(([A-Z0-9_./-]+)\)$")


@lru_cache(maxsize=1)
def _oncotree():
    """(display names, code -> name, lowercased name -> name)."""
    names, codes = set(), {}
    with open(config.ONCOTREE_TXT_FILE_PATH) as f:
        reader = csv.DictReader(f, delimiter="\t")
        levels = [c for c in (reader.fieldnames or []) if c.startswith("level_")]
        for row in reader:
            for col in levels:
                m = _LEVEL_VALUE.match((row.get(col) or "").strip())
                if m:
                    names.add(m.group(1))
                    codes[m.group(2)] = m.group(1)
    return names, codes, {n.lower(): n for n in names}


@lru_cache(maxsize=1)
def _gene_symbols():
    with open(config.GENE_LIST_FILE_PATH) as f:
        return {line.strip() for line in f if line.strip()}


@lru_cache(maxsize=4096)
def canonical_diagnosis(term):
    """
    The Oncotree display name for `term`, or None if there is no such node.

    Accepts the display name, the code, and either in any case.
    """
    if not term:
        return None
    term = str(term).strip()
    names, codes, lowered = _oncotree()
    if term in names:
        return term
    if term in codes:
        return codes[term]
    return lowered.get(term.lower())


@lru_cache(maxsize=4096)
def canonical_gene(symbol):
    """
    The HUGO symbol as it appears in the gene list, or None if absent.

    Only case is forgiven. Synonyms are deliberately not resolved here: that
    mapping is case-sensitive on purpose (WAS, CAN, MET and REST are live
    aliases of other genes) and runs earlier, in update_hugo_symbol.
    """
    if not symbol:
        return None
    symbol = str(symbol).strip()
    genes = _gene_symbols()
    if symbol in genes:
        return symbol
    upper = symbol.upper()
    return upper if upper in genes else None


def filter_diagnoses(diagnoses, trial_id=""):
    """Canonicalise a list of diagnoses, dropping unknown terms. Order-stable."""
    kept, seen = [], set()
    for term in diagnoses:
        name = canonical_diagnosis(term)
        if name is None:
            logger.warning(f"{trial_id}: dropped diagnosis not in Oncotree: {term!r}")
            continue
        if name != str(term).strip():
            logger.info(f"{trial_id}: rewrote diagnosis {term!r} -> {name!r}")
        if name not in seen:
            seen.add(name)
            kept.append(name)
    return kept


def filter_genomic_criteria(genomic_criteria, trial_id=""):
    """
    Drop CTML genomic entries whose hugo_symbol is not a known gene.

    Entries are {"genomic": {"hugo_symbol": ..., "variant_category": ...}};
    an entry carrying no symbol at all is left alone for the existing
    completeness checks to handle.
    """
    kept = []
    for entry in genomic_criteria or []:
        genomic = (entry or {}).get("genomic") if isinstance(entry, dict) else None
        symbol = (genomic or {}).get("hugo_symbol") if isinstance(genomic, dict) else None
        if not symbol:
            kept.append(entry)
            continue
        name = canonical_gene(symbol)
        if name is None:
            logger.warning(f"{trial_id}: dropped genomic criterion, "
                           f"{symbol!r} is not in {config.GENE_LIST_FILE_PATH}")
            continue
        genomic["hugo_symbol"] = name
        kept.append(entry)
    return kept
