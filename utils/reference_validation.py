"""
Validate model-proposed Oncotree diagnoses and HUGO symbols against the
reference files, and drop what does not exist.

Both genomic and diagnosis prompts hand the model the permitted vocabulary,
so every value it returns should already be drawn from these files. It is not:
benchmark runs produced `Leukemia` as an Oncotree diagnosis, `AML` (an Oncotree
*code*) where the display name belongs, and `H3` as a gene symbol alongside the
three real histone genes. None of these match a patient - CTML
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

# MatchMiner's own wildcards for "any solid tumour" and "any liquid tumour".
# They are valid values of oncotree_primary_diagnosis and are how a basket
# trial is expressed - see doc/nct_to_ctml_mapping_guide.md - but they are not
# Oncotree display names, so a plain lookup rejects them. The pipeline derives
# them deterministically from the trial's conditions, never from the model.
MATCHMINER_DIAGNOSIS_WILDCARDS = frozenset({"_SOLID_", "_LIQUID_"})

SYNONYM_TSV = config.GENE_SYNONYM_FILE_PATH
SYNONYM_ADDENDUM_TSV = config.GENE_SYNONYM_ADDENDUM_FILE_PATH
LEGACY_GENE_LIST = config.LEGACY_GENE_LIST_FILE_PATH


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


def gene_symbols():
    """The accept-list: every symbol a hugo_symbol field is allowed to hold."""
    return set(_gene_symbols())


def _read_synonym_rows():
    """
    Every (alias, official) row from the synonym table and the addendum, with
    the addendum's "!" blocklist applied.

    A leading "!" on an alias means "never resolve this one" - it is the
    addendum's way of vetoing a row NCBI supplies. PD-L1 is the standing
    example: the table maps it to CD274, but PD-L1 has its own biomarker path
    in the CTML schema, and letting it through as a gene would route it twice.
    The convention is honoured here rather than in each caller, because it was
    previously applied on the detection side and silently ignored on the
    validation side.

    Yields officials as written, so a multi-gene row ("RAS" -> KRAS,NRAS,HRAS)
    arrives intact and each caller decides what to do with it.
    """
    rows, blocked = [], set()
    for path in (SYNONYM_TSV, SYNONYM_ADDENDUM_TSV):
        try:
            handle = open(path, newline="")
        except FileNotFoundError:
            logger.warning(f"no gene synonym table at {path}")
            continue
        with handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) < 2:
                    continue
                alias, official = row[0].strip(), row[1].strip()
                if alias.startswith("!"):
                    blocked.add(alias[1:].strip())
                    continue
                rows.append((alias, official))
    return [(a, o) for a, o in rows if a not in blocked]


@lru_cache(maxsize=1)
def gene_synonym_mapping():
    """
    alias -> [official symbols], for finding genes named in criteria text.

    This is the input side of the gene reference: it decides which spellings
    in a trial's eligibility text are recognised as genes at all. It is
    deliberately permissive - three-character aliases and all - because a false
    positive here only costs an LLM call on a trial with no genomics, whereas a
    miss loses the criterion entirely. The output side is `canonical_gene`,
    which is strict; see the module docstring for why the two cannot share a
    table.

    Cached, so the returned dict is shared - read it, do not mutate it. It is
    a plain dict rather than the defaultdict this replaced, which silently
    grew a new empty entry on every lookup of a token that was not a gene.
    """
    mapping = {}
    for alias, official in _read_synonym_rows():
        mapping.setdefault(alias, []).append(official)
    return mapping


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
    for alias, official in _read_synonym_rows():
        # "," means the alias names several genes (RAS -> KRAS,NRAS,HRAS);
        # a hugo_symbol field holds one, so there is nothing to rewrite it to.
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

    Accepts the display name, the code, either in any case, and MatchMiner's
    _SOLID_ / _LIQUID_ wildcards.
    """
    if not term:
        return None
    term = str(term).strip()
    if term in MATCHMINER_DIAGNOSIS_WILDCARDS:
        return term
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


@lru_cache(maxsize=1)
def _expression_only_genes():
    """Genes whose criteria are about protein expression, not an alteration."""
    try:
        import src.trial_config as trial_config
        return {str(g).strip().upper()
                for g in getattr(trial_config, "expression_only_genes", ())}
    except Exception:
        return set()


def filter_genomic_criteria(genomic_criteria, trial_id=""):
    """
    Drop CTML genomic entries that cannot match a patient.

    Two reasons to drop. The symbol is not a gene the panel reports, or the
    gene is one whose eligibility criteria are about protein expression rather
    than a somatic alteration - see trial_config.expression_only_genes. Both
    produce the same silent failure if kept: MatchMiner matches genomic blocks
    against a sequencing report, so a criterion the report can never satisfy
    makes the trial invisible rather than merely wrong.

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
        if name.upper() in _expression_only_genes():
            logger.warning(
                f"{trial_id}: dropped genomic criterion on {name}. It is an "
                f"antigen or HLA restriction, measured by flow or IHC rather "
                f"than sequencing, so as a genomic requirement it would match "
                f"no patient."
            )
            continue
        genomic["hugo_symbol"] = name
        kept.append(entry)
    return kept


# Qualifiers ClinicalTrials.gov puts in front of a diagnosis in
# conditionsModule. Peeled only after the unmodified string has failed, so a
# real node whose name starts with one of these ("Primary Brain Tumor",
# "Malignant Peripheral Nerve Sheath Tumor") is matched before anything is
# stripped.
_CONDITION_QUALIFIER = re.compile(
    r"^(newly diagnosed|recurrent|refractory|relapsed|metastatic|advanced|"
    r"high[- ]risk|low[- ]risk|intermediate[- ]risk|childhood|paediatric|"
    r"pediatric|adult|primary|malignant|stage [0-9ivx]+|group [a-e])\s+",
    re.IGNORECASE)


# The same vocabulary appearing after the diagnosis instead of before it, which
# ClinicalTrials.gov does at least as often: "Medulloblastoma Recurrent",
# "Neuroblastoma, Recurrent, Refractory", "Medulloblastoma, Childhood". A comma
# before it is optional, and several can stack.
_TRAILING_QUALIFIER = re.compile(
    r"[,\s]+(newly diagnosed|recurrent|refractory|relapsed|in relapse|metastatic|"
    r"advanced|childhood|paediatric|pediatric|adult|nos)$",
    re.IGNORECASE)


def strip_condition_qualifiers(condition):
    """
    "High-Risk Neuroblastoma" and "Medulloblastoma Recurrent" -> the diagnosis.

    Leading and trailing qualifiers are peeled alternately until neither
    matches, so "Recurrent Childhood Medulloblastoma, Refractory" reduces in
    one call. Callers try the unmodified string first: several Oncotree nodes
    end in a word this would strip - "B-Lymphoblastic Leukemia/Lymphoma, NOS",
    "Mixed Phenotype Acute Leukemia, B/Myeloid, NOS" - and must match as
    themselves before anything is removed.
    """
    condition = (condition or "").strip()
    previous = None
    while previous != condition:
        previous = condition
        condition = _CONDITION_QUALIFIER.sub("", condition).strip()
        condition = _TRAILING_QUALIFIER.sub("", condition).strip()
    return condition


def diagnoses_from_conditions(conditions):
    """
    Oncotree terms the trial names outright in conditionsModule.

    Trials list their own diagnoses, and 27% of the cached corpus uses the
    exact Oncotree display name - "Neuroblastoma" is both. Reading that costs
    no tokens and cannot hallucinate, so it is worth doing before asking a
    model anything. Order-stable and deduplicated.

    Matching is exact rather than substring, deliberately: "Neoplasms, Brain"
    shares a substring with half the tree. The ", NOS" candidates are the one
    concession, and they are tried last so they only ever fire when nothing
    else matched. Oncotree suffixes its catch-all nodes that way and
    registries do not, so "Low-grade Glioma", "Glioma", "Sarcoma" and "Round
    Cell Sarcoma" each name a node this would otherwise miss. Ordering matters
    as much as the candidates: tried first, "Medulloblastoma" would pick up
    "Medulloblastoma, NOS" alongside the exact node it already matches, and
    the seed would start over-generating rather than merely reaching further.
    """
    found, seen = [], set()
    for condition in conditions or []:
        stripped = strip_condition_qualifiers(condition)
        for candidate in (condition, stripped, f"{condition}, NOS", f"{stripped}, NOS"):
            name = canonical_diagnosis(candidate)
            if name:
                if name not in seen:
                    seen.add(name)
                    found.append(name)
                break
    return found
