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

Retired gene symbols and aliases are rewritten rather than dropped. A model
answering HIST1H3A is right about the gene (H3C1) and out of date about its
spelling, so dropping it would discard a correct answer. Two sources feed the
rewrite: the fifteen renames between ref/genes_kispi.txt (the raw list as
supplied) and ref/genes.txt (current HGNC), always; and the synonym table,
filtered hard (see `_gene_aliases`).

The synonym table is NOT used as it stands. It is built for Aho-Corasick search
over criteria text, where a false positive costs one LLM call, and it maps
"ALL" to BCR, "AT" to BTK, "ARF" to CDKN2A, "H3" to H3C14 - and, at four
characters and up, "JMML" to PTPN11, "CHOP" to DDIT3, "PD-1" to PDCD1. Rewriting
model output through that would turn a paediatric trial's disease name into a
gene criterion, which is far worse than dropping an unrecognised symbol - a
drop is visible in the log, a wrong rewrite is not.
"""
import bisect
import csv
import re
from functools import lru_cache

from loguru import logger

import config
import utils.oncotree as onct

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
    rows, blocked = _synonym_table()
    return [(a, o) for a, o in rows if a not in blocked]


def _synonym_table():
    """(every (alias, official) row, the set of "!"-blocked aliases)."""
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
    return rows, blocked


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
    Alias or retired symbol -> panel symbol: every rewrite canonical_gene makes.

    The union of the Kispi renames (always, whatever their shape - CARS for
    CARS1 would fail the family rule below) and the widened synonym set. A
    rename wins a conflict, since Kispi listed it for exactly that gene.

    Until 2026-09-24 this was the renames alone, fifteen entries. That kept
    "ALL" out, but on the wrong criterion: HIST1H3B and HIST1H3C were rewritten
    because genes_kispi.txt happened to spell them that way, while HIST1H3A
    (H3C1) and HIST2H3C (H3C14) were dropped although the synonym table holds
    both. The DMG trials, whose literature spelling is the retired one, paid
    for it. Measured on the current ref files the set is now 4,028.
    """
    genes = _gene_symbols()
    renames = _legacy_renames(genes)
    return {**_panel_aliases(genes), **renames}


def _legacy_renames(genes):
    """
    Retired symbol -> current symbol, for the renames between the raw Kispi
    gene list and the current one. Every entry is a symbol Kispi themselves
    listed for a gene on the panel.
    """
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


# Every alias of three characters or fewer is refused. That is where the
# dangerous ones live - ALL, AT, ARF, H3, CAR, and 664 unambiguous panel
# aliases in all - and nothing worth rescuing is that short.
_REWRITE_MIN_LENGTH = 4

# "CD20", "CD117", "CD140a": cluster-of-differentiation names are how a trial
# states an immunophenotype (flow, IHC), not a sequencing result. Rewritten,
# "CD20+ lymphoma" becomes a required MS4A1 alteration and matches nobody -
# the failure trial_config.expression_only_genes exists to stop.
_CD_ANTIGEN = re.compile(r"^CD\d+[A-Za-z]?$")


def _alias_key(alias):
    """Case and punctuation folded: "PD-L1", "PDL1" and "pd-l1" share a key."""
    return re.sub(r"[^A-Z0-9]", "", alias.upper())


def _panel_aliases(genes):
    """
    alias -> panel symbol, for the synonym-table aliases safe to rewrite.

    An alias is kept only if every deterministic test passes. Counts are over
    the current ref files, applied in order (2026-09-24):

      4,879  unambiguous single-gene aliases of a panel gene that are not
             themselves a panel symbol in any case
      4,295  of them are >= _REWRITE_MIN_LENGTH characters
      4,269  are not the current symbol of another gene with a MANE
             transcript - TCF4 is a gene in its own right, not TCF7L2, and
             PDK1 is not PDPK1
      4,088  survive the four shape rules: no other gene shares the alias
             once case and punctuation are folded (p100 is NFKB2, P100 is
             PMEL); not a CD antigen; not the stem of two or more current
             symbols (PARP, HDAC, VEGF, PTCH - a family, not one gene); not a
             fusion name whose halves are different genes (BCR-ABL, EWS-FLI1 -
             the fusion path owns those); not a punctuation variant of an
             alias the addendum blocks ("PDL1" for "!PD-L1")
      4,027  are not in config.GENE_REWRITE_EXCLUSION_FILE_PATH, the rows
             that only measurement could find: aliases seen in the cached
             trial texts meaning something else (JMML, CHOP, ICF1, PD-1) and
             English words (FACE, TRAIL)

    Fails closed. Without the exclusion file the rules above would pass JMML
    to PTPN11, so a missing file disables the widening, not the check.
    """
    exclusions = _rewrite_exclusions()
    if exclusions is None:
        return {}

    rows, blocked = _synonym_table()
    blocked_keys = {_alias_key(b) for b in blocked}
    claims, owners_by_key = {}, {}
    for alias, official in rows:
        parts = [p.strip() for p in official.split(",") if p.strip()]
        claims.setdefault(alias, set()).update(parts)
        owners_by_key.setdefault(_alias_key(alias), set()).update(parts)
    for symbol in genes:
        owners_by_key.setdefault(_alias_key(symbol), set()).add(symbol)

    other_genes = _mane_genes() - genes
    symbols = sorted(_mane_genes() | genes)

    def is_family_stem(alias):
        stem = alias.upper()
        start = bisect.bisect_left(symbols, stem)
        count = 0
        for symbol in symbols[start:]:
            if not symbol.startswith(stem):
                break
            count += symbol != stem
        return count >= 2

    def names_one_gene(part):
        if part in genes or part in _mane_genes():
            return part
        owners = claims.get(part, set()) - {""}
        return next(iter(owners)) if len(owners) == 1 else None

    def is_fusion_name(alias):
        halves = [p for p in re.split(r"::|[-/:]", alias) if p]
        if len(halves) < 2:
            return False
        named = [names_one_gene(h) for h in halves]
        return all(named) and len(set(named)) >= 2

    kept = {}
    for alias, owners in claims.items():
        if alias in blocked:
            continue
        if len(owners) != 1:
            continue
        official = next(iter(owners))
        if (official not in genes or alias in genes or alias.upper() in genes
                or len(alias) < _REWRITE_MIN_LENGTH
                or alias in other_genes or alias.upper() in other_genes):
            continue
        key = _alias_key(alias)
        if (len(owners_by_key.get(key, ())) > 1
                or _CD_ANTIGEN.match(alias)
                or is_family_stem(alias)
                or is_fusion_name(alias)
                or key in blocked_keys
                or alias in exclusions):
            continue
        kept[alias] = official
    return kept


def _rewrite_exclusions():
    """Aliases listed in config.GENE_REWRITE_EXCLUSION_FILE_PATH, or None."""
    path = config.GENE_REWRITE_EXCLUSION_FILE_PATH
    try:
        handle = open(path, newline="")
    except FileNotFoundError:
        logger.warning(f"no gene rewrite exclusion list at {path}; only the "
                       f"Kispi renames will be rewritten")
        return None
    with handle:
        return {row[0].strip() for row in csv.reader(handle, delimiter="\t")
                if row and row[0].strip() and not row[0].lstrip().startswith("#")}


# Spelling differences that carry no information. Registries and Oncotree
# disagree about punctuation far more often than about medicine: "High Grade
# Glioma" for "High-Grade Glioma", "Wilms Tumor" for "Wilms' Tumor",
# "B Lymphoblastic Leukemia/Lymphoma" for "B-Lymphoblastic ...". Each of those
# used to fall through to the LLM, which then had to guess a branch of a tree
# it could not see - so a hyphen became a coin flip on the diagnosis.
#
# British spellings are folded for the same reason and are not hypothetical
# here: the CTIS half of the corpus is European, and "tumour" appears in EU
# trial records where ClinicalTrials.gov writes "tumor". Only endings that
# cannot change meaning are listed; no oncology term is distinguished from
# another by its -our/-or or -aemia/-emia spelling.
_FOLD_SUBSTITUTIONS = (
    ("tumour", "tumor"),
    ("leukaemia", "leukemia"),
    ("lymphoedema", "lymphedema"),
    ("anaemia", "anemia"),
    ("haemato", "hemato"),
    ("oesophag", "esophag"),
    ("paediatric", "pediatric"),
    ("coeliac", "celiac"),
)


def _fold(term):
    """
    A comparison key that ignores case, punctuation and British spelling.

    Commas survive because Oncotree uses them to carry meaning - "Glioma, NOS"
    and "Mixed Phenotype Acute Leukemia, B/Myeloid, NOS" are distinct nodes -
    while hyphens and slashes become spaces because the two vocabularies place
    them differently around identical terms.

    Verified against ref/oncotree_file.txt: all 879 display names fold to 879
    distinct keys, so folding merges nothing that Oncotree distinguishes. A
    test asserts this, because a future Oncotree release could introduce a
    genuine collision and it must fail loudly rather than pick a winner.
    """
    term = (term or "").lower().replace("'", "").replace("\u2019", "")
    for british, american in _FOLD_SUBSTITUTIONS:
        term = term.replace(british, american)
    term = re.sub(r"[-/]", " ", term)
    term = re.sub(r"[^a-z0-9, ]", " ", term)
    return re.sub(r"\s+", " ", term).strip()


@lru_cache(maxsize=1)
def _oncotree_folded():
    """Folded display name -> display name."""
    names, _, _ = _oncotree()
    folded = {}
    for name in sorted(names):
        folded.setdefault(_fold(name), name)
    return folded


@lru_cache(maxsize=1)
def _diagnosis_aliases():
    """
    Folded alias -> Oncotree display name, from config.DIAGNOSIS_SYNONYM_FILE_PATH.

    Two classes of row are dropped rather than trusted, both loudly:

    - a target that is not an Oncotree display name, which would put a string
      into CTML that matches no patient - the failure this module exists to
      prevent;
    - an alias that already resolves without the table, which is dead weight
      that cannot fire and would mislead the next person reading the file.

    The second check is what keeps the table honest as Oncotree moves. If a
    future release adds "Nephroblastoma" as a real node, that row starts
    warning instead of quietly shadowing nothing.
    """
    aliases = {}
    try:
        handle = open(config.DIAGNOSIS_SYNONYM_FILE_PATH)
    except FileNotFoundError:
        logger.warning(
            f"No diagnosis synonym table at {config.DIAGNOSIS_SYNONYM_FILE_PATH}; "
            f"registry spellings will only resolve by folding."
        )
        return aliases

    names, _, _ = _oncotree()
    folded_names = _oncotree_folded()
    with handle:
        for row in csv.reader(handle, delimiter="\t"):
            if not row or row[0].lstrip().startswith("#") or len(row) < 2:
                continue
            alias, target = row[0].strip(), row[1].strip()
            if not alias or not target:
                continue
            if target not in names:
                logger.warning(
                    f"Diagnosis synonym {alias!r} -> {target!r} dropped: the target "
                    f"is not an Oncotree display name."
                )
                continue
            key = _fold(alias)
            if key in folded_names:
                logger.warning(
                    f"Diagnosis synonym {alias!r} -> {target!r} dropped: {alias!r} "
                    f"already resolves to {folded_names[key]!r} without the table."
                )
                continue
            aliases[key] = target
    return aliases


@lru_cache(maxsize=4096)
def canonical_diagnosis(term):
    """
    The Oncotree display name for `term`, or None if there is no such node.

    Accepts the display name, the code, either in any case, MatchMiner's
    _SOLID_ / _LIQUID_ wildcards, a spelling that differs only in punctuation
    or British/American convention, and the curated aliases in
    ref/diagnosis_synonyms.tsv.

    Order is deliberate and runs from most to least literal. Folding is tried
    before the alias table so that no curated entry can shadow a real Oncotree
    name: a table is edited by hand and the tree is not, so the tree wins.
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
    exact_case_insensitive = lowered.get(term.lower())
    if exact_case_insensitive:
        return exact_case_insensitive
    key = _fold(term)
    folded = _oncotree_folded().get(key)
    if folded:
        return folded
    return _diagnosis_aliases().get(key)


@lru_cache(maxsize=4096)
def canonical_gene(symbol):
    """
    The HUGO symbol as it appears in the gene list, or None if absent.

    Case is forgiven, and a retired symbol or alias is rewritten to the panel
    symbol it names, through the filtered set in `_gene_aliases`: HIST1H3A to
    H3C1, WHSC1 to NSD2, INI1 to SMARCB1. Nothing upstream does this:
    update_hugo_symbol rewrites HER2 to ERBB2 and nothing else, and the raw
    synonym table is used only to *find* genes in criteria text.

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


# Rearranging immunoglobulin and T-cell receptor loci. They are HGNC symbols
# (IGH is HGNC:5477) and common fusion partners (IGH::CRLF2, IGH::MYC), but
# a locus has no MANE transcript, so ref/mane_genes.tsv cannot list them.
FUSION_PARTNER_LOCI = frozenset({"IGH", "IGK", "IGL", "TRA", "TRB", "TRG", "TRD"})


@lru_cache(maxsize=1)
def _mane_genes():
    with open(config.MANE_GENES_FILE_PATH) as handle:
        rows = [line.rstrip("\n").split("\t") for line in handle if not line.startswith("#")]
    return frozenset(row[0] for row in rows[1:] if row and row[0])


def fusion_partner(symbol):
    """
    (symbol, status) for a fusion partner named by a trial.

    A partner need not be on the panel: RUNX1::RUNX1T1 is reported by the
    fusion caller although RUNX1T1 is not a panel gene. So the order is:
    a panel gene or its alias (as canonical_gene), then any current symbol
    with a MANE Select transcript, then the immunoglobulin/TCR loci. Only
    exact symbols are accepted off-panel - the alias table covers the panel
    alone, and guessing an alias across 19,000 genes is how "CAR" (as in
    CAR-T) would become PRKAR1A.

    status is "panel", "off_panel", "locus", or "unknown" with symbol None.
    """
    if not symbol:
        return None, "unknown"
    on_panel = canonical_gene(symbol)
    if on_panel:
        return on_panel, "panel"
    token = str(symbol).strip()
    for candidate in (token, token.upper()):
        if candidate in _mane_genes():
            return candidate, "off_panel"
        if candidate in FUSION_PARTNER_LOCI:
            return candidate, "locus"
    return None, "unknown"


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
# "stage [0-9ivx]+[ab]?" rather than "stage [0-9ivx]+": ClinicalTrials.gov
# writes "Stage IIIB", and leaving the substage attached blocked the match.
# "untreated", "unresectable", "extracranial" and "extragonadal" are likewise
# observed in the cached corpus, not anticipated.
_CONDITION_QUALIFIER = re.compile(
    r"^(newly diagnosed|previously treated|untreated|recurrent|refractory|"
    r"relapsed|metastatic|advanced|unresectable|"
    r"high[- ]risk|low[- ]risk|intermediate[- ]risk|childhood|paediatric|"
    r"pediatric|adult|primary|malignant|extracranial|extragonadal|"
    r"stage [0-9ivx]+[ab]?|group [a-e])\s+",
    re.IGNORECASE)


# The same vocabulary appearing after the diagnosis instead of before it, which
# ClinicalTrials.gov does at least as often: "Medulloblastoma Recurrent",
# "Neuroblastoma, Recurrent, Refractory", "Medulloblastoma, Childhood". A comma
# before it is optional, and several can stack.
# "AJCC v6 and v7" is the staging-manual citation NCI appends to its germ cell
# and sarcoma conditions - "Stage I Testicular Seminoma AJCC v6 and v7" - and
# it is provenance, not diagnosis. "relapse" as a bare noun joins "in relapse"
# because ClinicalTrials.gov writes both ("Acute Lymphoid Leukemia Relapse").
_TRAILING_QUALIFIER = re.compile(
    r"[,\s]+(newly diagnosed|recurrent|refractory|relapsed|relapse|in relapse|"
    r"metastatic|advanced|childhood|paediatric|pediatric|adult|nos|"
    r"ajcc v[0-9]+( and v[0-9]+)*)$",
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


def _words(name):
    """The set of words in a display name, ignoring case and punctuation."""
    return set(re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("-", " ")).split())


def _widen_inferred_nos_leaf(name, condition, trial_id=""):
    """
    Swap an inferred ", NOS" leaf for an ancestor that actually matches patients.

    Oncotree suffixes its catch-all nodes ", NOS", and MatchMiner expands a
    diagnosis to its descendants before querying - so a leaf expands to itself
    alone. Verified against the deployed oncotree_mapping.json on 2026-09-21:
    "Glioma, NOS" reaches 1 patient code where its parent "Diffuse Glioma"
    reaches 24. A trial registering the condition "Glioma" therefore enrolled
    against a term matching almost nobody, and the benchmark scored it correct,
    because it compares strings and the deployment expands them.

    Two guards, because widening trades a false negative for a false positive
    and only one of those is visible to a clinician.

    Climbing stops below level_1. "Sarcoma, NOS" sits directly under the
    "Soft Tissue" root, and promoting it would enrol every soft-tissue tumour
    while still missing the bone sarcomas - Ewing, osteosarcoma - that a
    sarcoma trial means.

    The parent must also keep every word the leaf states. A catch-all may
    generalise, but it may not silently drop a restriction: "High-Grade
    Glioma, NOS" sits under "Diffuse Glioma", so promoting it would enrol
    low-grade patients into a high-grade trial, and "Low-Grade Glioma, NOS"
    sits under "Encapsulated Glioma", which is not where low-grade gliomas
    generally live. Across the tree this widens the eight true catch-alls -
    "Medulloblastoma, NOS" to "Medulloblastoma", "B-Lymphoblastic
    Leukemia/Lymphoma, NOS" to its parent, the case verified against two
    loaded trials in MatchMiner - and leaves the twenty qualifier-bearing
    leaves alone.

    Note the ancestor is not always complete cover either: "Diffuse Glioma"
    excludes the encapsulated and angiocentric gliomas filed elsewhere in the
    tree. It is the tree's own placement of the catch-all node, and 24 codes
    beat 1, but a trial whose population is genuinely "any glioma" still wants
    a human.
    """
    if not name.endswith(", NOS"):
        return name
    parent_of, level_1_names, descendants = onct.get_lineage()
    if len(descendants.get(name, {name})) > 1:
        return name  # already expands; nothing to fix
    parent = parent_of.get(name)
    drops_a_qualifier = parent and not _words(name[:-len(", NOS")]) <= _words(parent)
    if (not parent or parent in level_1_names
            or len(descendants.get(parent, ())) <= 1 or drops_a_qualifier):
        logger.warning(
            f"{trial_id} | Condition {condition!r} resolves only to {name!r}, which "
            f"matches one patient code, and no ancestor widens it without dropping a "
            f"restriction it states or reaching an organ-system root. Keeping it; a "
            f"curator should decide what population this trial actually wants."
        )
        return name
    logger.info(
        f"{trial_id} | Condition {condition!r} inferred {name!r}, which expands to "
        f"itself alone. Using its parent {parent!r} instead, which expands to "
        f"{len(descendants[parent])} terms and so matches the patients the leaf "
        f"would miss."
    )
    return parent


def diagnoses_from_conditions(conditions, trial_id=""):
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
        candidates = (condition, stripped, f"{condition}, NOS", f"{stripped}, NOS")
        for position, candidate in enumerate(candidates):
            name = canonical_diagnosis(candidate)
            if name:
                # Positions 2 and 3 are the ", NOS" suffix this function added.
                # The trial did not say NOS, so the leaf is our inference and
                # is open to correction; a trial that writes "Glioma, NOS"
                # itself matches at position 0 and is left alone.
                if position >= 2:
                    name = _widen_inferred_nos_leaf(name, condition, trial_id)
                if name not in seen:
                    seen.add(name)
                    found.append(name)
                break
    return found
