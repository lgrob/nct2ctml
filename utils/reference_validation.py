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

Retired gene symbols are rewritten rather than dropped, but only the fifteen
that Kispi's own list actually used. ref/genes.txt holds current HGNC symbols;
ref/genes_kispi.txt is the raw list as supplied, and the difference between the
two is exactly a set of renames - H3F3B for H3-3B, WHSC1 for NSD2, SEPT9 for
SEPTIN9. A model answering with one of those is right about the gene and out of
date about its spelling, so dropping it would discard a correct answer.

The full synonym table is deliberately NOT used for this. It is built for
Aho-Corasick search over criteria text, where a separate blocklist guards the
short entries, and it contains 584 aliases of three characters or fewer:
"ALL" resolves to BCR, "AT" to BTK, "ARF" to CDKN2A, "H3" to H3C14. Rewriting
model output through it would turn a paediatric trial's "ALL" into a BCR
criterion, which is far worse than dropping an unrecognised symbol - a drop is
visible in the log, a wrong rewrite is not.
"""
import csv
import re
from functools import lru_cache

from loguru import logger

import config

# "Acute Myeloid Leukemia (AML)" -> name, code. Codes are upper-case with
# digits and a few separators; anything else is a name containing brackets.
_LEVEL_VALUE = re.compile(r"^(.*)\s+\(([A-Z0-9_./-]+)\)$")

# Same paths TrialMapManager.load_gene_synonym_mapping opens; they are not in
# config.py, so they are spelled out here rather than silently diverging.
SYNONYM_TSV = "ref/synonym_to_gene_symbol.tsv"
SYNONYM_ADDENDUM_TSV = "ref/gene_synonym_addendum.tsv"
# The raw gene list as Kispi supplied it, before symbols were brought up to
# current HGNC. Nothing else reads it; here it is the authority on which
# retired spellings are worth rewriting.
LEGACY_GENE_LIST = "ref/genes_kispi.txt"


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


@lru_cache(maxsize=1)
def _gene_aliases():
    """
    Retired symbol -> current symbol, for the renames between the raw Kispi
    gene list and the current one.

    Restricting the rewrite to this set is the point. Every entry is a symbol
    Kispi themselves listed for a gene that is on the panel, so the rewrite can
    only ever recover a gene the pipeline is entitled to name. Opening it to
    the whole synonym table would admit "ALL" -> BCR; see the module docstring.
    """
    genes = _gene_symbols()
    try:
        with open(LEGACY_GENE_LIST) as f:
            retired = {line.strip() for line in f if line.strip()} - genes
    except FileNotFoundError:
        logger.warning(f"no legacy gene list at {LEGACY_GENE_LIST}; retired "
                       f"symbols will be dropped rather than rewritten")
        return {}

    claims = {}
    for path in (SYNONYM_TSV, SYNONYM_ADDENDUM_TSV):
        try:
            handle = open(path, newline="")
        except FileNotFoundError:
            continue
        with handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) < 2:
                    continue
                alias, official = row[0].strip(), row[1].strip()
                # "," means the alias names several genes (RAS -> KRAS,NRAS,
                # HRAS); a hugo_symbol field holds one, so there is nothing to
                # rewrite it to.
                if alias not in retired or "," in official or official not in genes:
                    continue
                claims.setdefault(alias, set()).add(official)

    unresolved = retired - set(claims)
    if unresolved:
        logger.debug(f"retired symbols with no unambiguous current name: "
                     f"{sorted(unresolved)}")
    return {alias: next(iter(owners)) for alias, owners in claims.items()
            if len(owners) == 1}


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

    Case is forgiven, and a retired symbol is rewritten to the current one.
    Nothing upstream does this: update_hugo_symbol rewrites HER2 to ERBB2 and
    nothing else, and the synonym table is otherwise used only to *find* genes
    in criteria text, never to normalise what the model answers with.

    The alias lookup stays case-sensitive on purpose. WAS, CAN, MET and REST
    are live aliases of other genes, so lower-casing the table would make
    ordinary words resolve to genes.
    """
    if not symbol:
        return None
    symbol = str(symbol).strip()
    genes = _gene_symbols()
    if symbol in genes:
        return symbol
    upper = symbol.upper()
    if upper in genes:
        return upper
    return _gene_aliases().get(symbol)


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
