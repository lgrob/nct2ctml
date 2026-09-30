"""
Deterministic checks over a trial's text, shared by the mapper and the
review helper.

- Finding mentions: find_mentions, with British/American spelling and gene
  names glued to a protein change, and Reference, which knows every way a
  diagnosis or gene is written (Oncotree names, synonym tables, curated
  text terms).
- Rules the mapper applies after the model and the review helper re-applies
  to existing output: diagnoses named only in the exclusion criteria, genes
  required although the text says absent or irrelevant, and ALL named
  without a lineage (T-ALL added beside B-ALL).
- Walking a CTML match tree: collect, _genomic_nodes, add_sibling_*.

Moved from utils/review_helper.py on 2026-09-29 (improvement plan step 11,
phase 1.1) so that the mapper no longer imports the review tool. No model
calls; the same input always gives the same answer.
"""

import re
from collections.abc import Iterable
from typing import Any

import config
import utils.gene_mentions as gene_mentions
import utils.reference_validation as rv
from utils.oncotree import get_lineage

# British/American variants, applied per word when searching for a diagnosis.
_SPELLING = [
    ("leukemia", "leuka?emia"),
    ("tumor", "tumou?r"),
    ("hemato", "ha?emato"),
    ("esophag", "o?esophag"),
    ("anemia", "ana?emia"),
    ("hemangio", "ha?emangio"),
]


def _walk(node, out, include=None):
    """Collect diagnoses, genomic criteria and ages from a CTML match tree."""
    if isinstance(node, list):
        for x in node:
            _walk(x, out, include)
        return
    if not isinstance(node, dict):
        return
    clinical = node.get("clinical")
    if isinstance(clinical, dict):
        dx = clinical.get("oncotree_primary_diagnosis")
        for d in dx if isinstance(dx, list) else [dx]:
            if d:
                out["diagnoses"].append(str(d))  # "!Name" kept: an excluded diagnosis
        if clinical.get("age_numerical"):
            out["ages"].append(str(clinical["age_numerical"]))
    genomic = node.get("genomic")
    if isinstance(genomic, dict):
        out["genomic"].append(genomic)
    for k, v in node.items():
        if k not in ("clinical", "genomic"):
            _walk(v, out, include)


def collect(ctml: dict) -> dict[str, list]:
    out: dict[str, list] = {"diagnoses": [], "ages": [], "genomic": []}
    _walk(ctml.get("treatment_list", ctml), out)
    return out


def _gene_aliases():
    inverse = {}
    for alias, symbols in rv.gene_synonym_mapping().items():
        for s in symbols:
            inverse.setdefault(s, set()).add(alias)
    return inverse


def _term_pattern(term, right=r"(?![A-Za-z0-9])"):
    words = re.split(r"[\s\-/,]+", term.strip())
    parts = []
    for w in words:
        if not w:
            continue
        p = re.escape(w.lower())
        for us, either in _SPELLING:
            p = p.replace(us, either)
        parts.append(p)
    return r"(?<![A-Za-z0-9])" + r"[\s\-/,]+".join(parts) + right


_ALTERATION = (
    r"(?:mutations?|mutated|mutant|alterations?|fusions?|rearrangements?|amplification|"
    r"translocation|variants?|positiv\w*|deletion)"
)


def _gene_status_patterns(term):
    t = re.escape(term)
    irrelevant = [
        rf"with\s*(?:or|/)\s*without\s+(?:an?\s+)?{t}\b",
        rf"(?:mutant|mutated|positive)\s+or\s+(?:wild[\s-]*type|negative)\s+{t}",
        rf"(?<![A-Za-z0-9]){t}\b[^.;]{{0,40}}(?:mutant|mutated|positive)\s+or\s+(?:wild[\s-]*type|negative)",
    ]
    negative = [
        rf"wild[\s-]*type\s+(?:for\s+)?{t}\b",
        rf"(?<![A-Za-z0-9]){t}[\s-]*wild[\s-]*type",
        rf"(?<![A-Za-z0-9]){t}[\s-]*(?:wt|WT)\b",
        rf"(?<![A-Za-z0-9]){t}[\s-]*negative",
        rf"(?:without|no|absence of|lack of|not harbou?ring|negative for)\s+(?:an?\s+|any\s+|known\s+|the\s+)?{t}\b",
    ]
    positive = [
        rf"(?<![A-Za-z0-9]){t}[\s-]*{_ALTERATION}",
        rf"(?:with|harbou?ring|positive for|carrying)\s+(?:an?\s+)?{t}\b",
        rf"(?<![A-Za-z0-9]){t}\s*\+",
    ]
    return irrelevant, negative, positive


def gene_status_contradictions(
    ctml: dict | None, inclusion: str | None, ref: "Reference | None" = None
) -> dict[str, str]:
    """
    Genes the match tree requires although the inclusion text says they must
    be absent or do not matter: "wild type FLT-ITD" read as an FLT3 mutation
    (NCT05805605, reported 2026-09-27), "no known EGFR ... mutations", "HER2
    negative", "with or without NPM1 mutation", "either mutant or wild-type
    B-RAF". A gene the text also states positively (two routes, e.g. MYCN
    amplified or not) is not reported. Deterministic, no model call.

    Returns {gene: sentence fragment}. Measured over all indexed trials on
    2026-09-27: 7 trials flagged, all 7 real errors; 2 false alarms among 56
    reviewed trials (Ewing-like sarcoma "negative for EWSR1 rearrangement",
    where the EWSR1-positive route is only implied).
    """
    ref = ref or _shared_reference()
    text = (inclusion or "").replace("\\[", "[").replace("\\]", "]")

    def negated(g):
        return any(
            str(g.get(k, "")).startswith("!")
            for k in ("variant_category", "cnv_call", "protein_change")
        )

    required = sorted(
        {
            g.get("hugo_symbol")
            for g in _genomic_nodes((ctml or {}).get("treatment_list"))
            if g.get("hugo_symbol") and not negated(g)
        }
    )
    out = {}
    for gene in required:
        terms = [x for x in ref.gene_terms(gene) if len(x) >= 3] + (
            ["FLT3-ITD", "FLT-ITD"] if gene == "FLT3" else []
        )
        irr, neg, pos = [], [], []
        for x in terms:
            i_p, n_p, p_p = _gene_status_patterns(x)
            irr += [m for p in i_p for m in re.finditer(p, text, re.I)]
            neg += [m for p in n_p for m in re.finditer(p, text, re.I)]
            pos += [m for p in p_p for m in re.finditer(p, text, re.I)]
        neg = [
            m
            for m in neg
            if not any(i.start() <= m.start() <= i.end() for i in irr)
            and not re.search(r"with\s*(?:or|/)\s*$", text[max(0, m.start() - 9) : m.start()], re.I)
        ]
        pos = [m for m in pos if not any(n.start() <= m.start() < n.end() + 5 for n in neg + irr)]
        hit = irr[0] if irr else (neg[0] if neg and not pos else None)
        if hit:
            out[gene] = " ".join(text[max(0, hit.start() - 60) : hit.end() + 40].split())
    return out


def diagnoses_only_in_exclusions(
    diagnoses: Iterable,
    inclusion: str | None,
    exclusion: str | None,
    context: Iterable[str] = (),
    ref: "Reference | None" = None,
) -> list[str]:
    """
    Diagnoses named (by name or synonym) in the exclusion criteria and nowhere
    in the inclusion criteria or the context texts (title, conditions).

    The mapper reads the whole eligibility text and can turn "Exclusion: JMML,
    APL, Down syndrome leukaemia" into eligible diagnoses (2023-504999-25-00,
    reported 2026-09-26). On the first full run's 1,171 trials this found 113
    diagnoses in 75 trials, 69 of them published as mapped; 10 of 10 sampled
    were real errors. A diagnosis the text does not name at all is not
    reported: that is the normal case for a subtype (see
    doc/open_issues.md on text support).
    """
    ref = ref or _shared_reference()
    other = " ".join([inclusion or ""] + [t for t in context if t])
    out = []
    for d in dict.fromkeys(diagnoses or []):
        d = str(d)
        if d.startswith(("!", "_")) or d not in ref.names:
            continue
        terms = ref.dx_terms(d)
        if find_mentions(exclusion or "", terms) and not find_mentions(other, terms):
            out.append(d)
    return out


_SHARED: list["Reference"] = []


def _shared_reference():
    """One Reference per process, so the mapper does not reload it per trial."""
    if not _SHARED:
        _SHARED.append(Reference())
    return _SHARED[0]


B_ALL = "B-Lymphoblastic Leukemia/Lymphoma"


T_ALL = "T-Lymphoblastic Leukemia/Lymphoma"


# MatchMiner's basket wildcards, as diagnosis names.
WILDCARD_NAMES = frozenset({"_SOLID_", "_LIQUID_"})


# A condition that describes a population rather than a diagnosis, which is what
# src.trial_data_helper.all_tumours / all_solid_tumours read as a basket.
_CONDITION_IS_BROAD = re.compile(
    r"\b(?:solid\s+tumou?rs?|solid\s+malignanc|metastatic\s+cancer|malignant\s+neoplasm|neoplasms|"
    r"cancer|advanced\s+cancer)\b",
    re.I,
)


_ALL_FULL = re.compile(r"acute\s+lymph(?:oblastic|ocytic|oid)\s+leuka?emia", re.I)


_ALL_ABBR = re.compile(r"(?<![A-Za-z-])ALL(?![A-Za-z-])")  # capitals only: not the word "all"


_B_LINEAGE = re.compile(
    r"\bB[\s-]*(?:cell\s*)?(?:ALL|acute|precursor|lineage|lymphoblastic|LBL)|\bBCP\b|CD19|CD22|CD20|\bPh\s*\+|"
    r"Philadelphia|BCR[\s:-]*ABL|pre-?B|blinatumomab|inotuzumab|tisagenlecleucel|brexucabtagene|"
    r"obecabtagene|KMT2A-r|infant",
    re.I,
)


_T_LINEAGE = re.compile(
    r"\bT[\s-]*(?:cell\s*)?(?:ALL|acute\s+lymphoblastic|lymphoblastic|LBL)\b|T-lineage", re.I
)


def all_lineage_unspecified(
    diagnoses: Iterable, inclusion: str | None, exclusion: str | None, context: Iterable[str] = ()
) -> bool:
    """
    True when a trial names acute lymphoblastic leukaemia without a lineage
    and the mapping has B-ALL but not T-ALL.

    ref/diagnosis_synonyms.tsv maps unqualified ALL to B-ALL (Oncotree has
    no lineage-free ALL node), so a T-ALL patient did not match a trial for
    "ALL". Not reported when any B- or T-lineage wording appears (CD19, Ph+,
    B-cell, blinatumomab, T-ALL named or excluded) or the trial already has
    T-ALL or _LIQUID_. Measured 2026-09-27: 20 indexed trials.
    """
    dx = {str(d) for d in diagnoses or []}
    if B_ALL not in dx or T_ALL in dx or "!" + T_ALL in dx or "_LIQUID_" in dx:
        return False
    ctx = " ".join(c for c in context if c)
    named = (
        _ALL_FULL.search(inclusion or "")
        or _ALL_ABBR.search(inclusion or "")
        or _ALL_FULL.search(ctx)
    )
    if not named:
        return False
    both = " ".join([inclusion or "", ctx])
    return not (
        _B_LINEAGE.search(both) or _T_LINEAGE.search(both) or _T_LINEAGE.search(exclusion or "")
    )


# "18-70 years", "18 to 70 years", "18 and 70 yrs": both ends of a range.
_YEAR_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|\u2013|\u2014|to|and|~)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", re.I
)


# "18 years", ">= 18 years of age".
_YEAR_ONE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", re.I)


# Registry units below a year, as clinicaltrials.gov writes them.
_SUB_YEAR_UNIT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(day|week|month)s?\s*$", re.I)


def age_units_implausible(minimum_raw, maximum_raw, inclusion: str | None) -> str:
    """
    The reason the structured age fields contradict the text's own units, or
    "" when they do not.

    Reported when both structured bounds are in days, weeks or months AND the
    inclusion text states the same two numbers in years. That combination is a
    sponsor's data-entry error, not a neonatal trial: NCT06342336 and
    NCT07106892 publish minimumAge "18 Days" / maximumAge "75 Days" against
    "18 years to 75 years" in the text, and NCT06776952 "18 Days" / "70 Days"
    against "Aged 18-70 years (inclusive)". All three also carry
    stdAges CHILD, which is why an adult trial is in a paediatric corpus at
    all. Found by the 2026-09-29 audit (defect B).

    The numbers must match for the check to fire, so a real neonatal study
    ("18 to 75 days") is not reported, and neither is a year figure that
    appears elsewhere in the text for another purpose. The mapper keeps the
    structured reading - it is what the registry says - and routes the trial
    to review rather than guessing which field the sponsor meant.
    """
    low, high = (
        _SUB_YEAR_UNIT.match(str(minimum_raw or "")),
        _SUB_YEAR_UNIT.match(str(maximum_raw or "")),
    )
    if not (low and high):
        return ""
    in_years: set[float] = set()
    for a, b in _YEAR_RANGE.findall(inclusion or ""):
        in_years.update((float(a), float(b)))
    in_years.update(float(n) for n in _YEAR_ONE.findall(inclusion or ""))
    stated = (float(low.group(1)), float(high.group(1)))
    if not in_years.issuperset(stated):
        return ""
    return (
        f"the registry states {minimum_raw} to {maximum_raw}, and the inclusion text "
        f"states the same numbers in years"
    )


def diagnosis_seed_suspect(
    diagnoses: Iterable,
    conditions: Iterable[str],
    inclusion: str | None,
    context: Iterable[str] = (),
) -> str:
    """
    The reason this trial's diagnosis scope looks wrong on deterministic grounds,
    or "" when it does not. Two cases, both from the 2026-09-29 audit and both
    measured over all 1,146 indexed trials
    (doc/decisions/2026-09-29-conditions-seed-rules.md):

    1. **A basket resting on the word "oncology".** `all_tumours` reads a sole
       condition of "cancer", "oncology" or "advanced cancer" as every tumour, so
       the trial is published with both wildcards. "Oncology" is a specialty, not
       a population: NCT04217512 registers it and its inclusion text is "Patients
       with head and neck cancer"; NCT07633236 registers "Oncology Patients
       Receiving Chemotherapy" beside "Cachexia-Anorexia Syndrome". 2 of the 17
       trials whose basket rests on a bare broad word, and both are wrong. The
       wider rule on "cancer" was measured and not adopted: 10 of its 17 are
       category headers the basket rule is right about.
    2. **B-lineage published where the text names only T-lineage.** Oncotree has
       no lineage-free ALL node, so `ref/diagnosis_synonyms.tsv` maps unqualified
       ALL to B-ALL. A T-cell trial that registers "Acute Lymphoblastic Leukemia"
       therefore gets a B-lineage criterion it never asked for (NCT07070219,
       NCT07070323). 8 indexed trials.

    Nothing is removed. The flag routes the trial to review, because both cases
    need a person: case 1 may be a genuine basket whose text happens to name one
    tumour, and case 2 may be a trial that does enrol both lineages.
    """
    names = {str(d) for d in diagnoses or []}
    positive = {n for n in names if not n.startswith("!")}
    text = " ".join([inclusion or "", " ".join(c for c in context if c)])

    if positive & WILDCARD_NAMES:
        broad = [c for c in conditions or [] if "oncology" in c.lower()]
        others = [
            c for c in conditions or [] if c not in broad and _CONDITION_IS_BROAD.search(c or "")
        ]
        specific = positive - WILDCARD_NAMES
        if broad and not others and (specific or _ALL_FULL.search(text)):
            return (
                f"the basket rests on the condition {broad[0].strip()!r}, a specialty rather "
                f"than a population"
                + (f", and the trial also names {sorted(specific)[0]}" if specific else "")
            )

    t_lineage = _T_LINEAGE.search(text)
    if B_ALL in positive and t_lineage and not _B_LINEAGE.search(text):
        return (
            f"{B_ALL} is required although the text names T-lineage disease "
            f"({t_lineage.group(0)!r}) and never B-lineage"
        )
    return ""


def add_sibling_diagnosis(tree: Any, existing: str, new: str) -> int:
    """
    Add `new` as an alternative wherever `existing` is an eligible diagnosis:
    beside it in an OR list, or by wrapping a lone node in an OR. The copy
    keeps the node's other clinical fields (age, sex). Returns the count.
    """
    import copy

    count = 0

    def is_it(n):
        return (
            isinstance(n, dict)
            and isinstance(n.get("clinical"), dict)
            and n["clinical"].get("oncotree_primary_diagnosis") == existing
        )

    def twin(n):
        c = copy.deepcopy(n)
        c["clinical"]["oncotree_primary_diagnosis"] = new
        return c

    def walk(node, parent_key=None):
        nonlocal count
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            i = 0
            while i < len(node):
                n = node[i]
                if is_it(n):
                    count += 1
                    if parent_key == "or":
                        node.insert(i + 1, twin(n))
                        i += 1
                    else:
                        node[i] = {"or": [n, twin(n)]}
                else:
                    walk(n, parent_key)
                i += 1

    walk(tree)
    return count


def add_sibling_gene(tree: Any, existing: str, new: str) -> int:
    """
    Give every genomic criterion on `existing` a twin on `new` with the same
    fields: beside it in an OR list; for an exclusion ('!...') under an AND,
    beside it in the AND (both must be absent); a lone required criterion is
    wrapped in an OR. Skips lists that already hold `new`. Returns the count.
    """
    import copy

    count = 0

    def gene(n):
        return (
            n.get("genomic", {}).get("hugo_symbol")
            if isinstance(n, dict) and isinstance(n.get("genomic"), dict)
            else None
        )

    def walk(node, parent_key=None):
        nonlocal count
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            if any(gene(n) == new for n in node):
                return
            i = 0
            while i < len(node):
                n = node[i]
                if gene(n) == existing:
                    twin = copy.deepcopy(n)
                    twin["genomic"]["hugo_symbol"] = new
                    negated = str(n["genomic"].get("variant_category", "")).startswith("!")
                    count += 1
                    if parent_key == "or" or negated:
                        node.insert(i + 1, twin)
                        i += 1
                    else:
                        node[i] = {"or": [n, twin]}
                else:
                    walk(n, parent_key)
                i += 1

    walk(tree)
    return count


def _genomic_nodes(node):
    if isinstance(node, dict):
        if isinstance(node.get("genomic"), dict):
            yield node["genomic"]
        for v in node.values():
            yield from _genomic_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _genomic_nodes(v)


def find_mentions(
    text: str, terms: Iterable[str], case_sensitive_short: bool = True, gene: str | None = None
) -> list[tuple[int, int, str]]:
    """
    [(start, end, term)] for whole-word mentions of any term in text.

    With `gene`, the terms are names of that gene, and a name glued to a
    protein change counts too ("H3.3K27M", "EGFRvIII"), as in the scan
    (utils/gene_mentions).
    """
    hits: list[tuple[int, int, str]] = []
    for t in sorted({t for t in terms if t}, key=len, reverse=True):
        flags = 0 if (case_sensitive_short and len(t) <= 4) else re.IGNORECASE
        if gene:
            right = gene_mentions.right_boundary(gene)
            pattern = (
                _term_pattern(t, right) if flags else r"(?<![A-Za-z0-9])" + re.escape(t) + right
            )
        else:
            pattern = (
                _term_pattern(t)
                if flags
                else r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])"
            )
        for m in re.finditer(pattern, text, flags):
            if not any(s < m.end() and m.start() < e for s, e, _ in hits):
                hits.append((m.start(), m.end(), t))
    return sorted(hits)


class Reference:
    """Reference data loaded once per run."""

    def __init__(self):
        self.parent, self.level1, self.descendants = get_lineage()
        self.names = set(self.descendants)
        self.aliases = {}
        self.text_terms = {}
        try:
            with open(
                getattr(config, "DIAGNOSIS_TEXT_TERMS_FILE_PATH", "ref/diagnosis_text_terms.tsv")
            ) as fh:
                for line in fh:
                    if line.startswith("#") or not line.strip():
                        continue
                    name, term = line.rstrip("\n").split("\t")[:2]
                    self.text_terms.setdefault(name, set()).add(term)
        except FileNotFoundError:
            pass
        for alias, name in rv._diagnosis_aliases().items():
            self.aliases.setdefault(name, set()).add(alias)
        self.gene_aliases = _gene_aliases()
        self.synonyms = rv.gene_synonym_mapping()
        self.curated = rv.curated_aliases()
        self.curated_groups = rv.curated_group_aliases()

    def dx_terms(self, name: str) -> set[str]:
        """
        Terms that count as the text naming a diagnosis: the Oncotree name
        (with and without ", NOS"), the synonym-table aliases, the text terms
        in ref/diagnosis_text_terms.tsv, and for each its singular or plural
        and apostrophe-free form ("Myelodysplastic Syndrome", "Wilms Tumor").
        Until 2026-09-27 only the first two, so "myelodysplastic syndrome
        (MDS)" and "acute promyelocytic leukaemia (APL)" were not found.
        """
        base = (
            {name, re.sub(r",\s*NOS$", "", name)}
            | self.aliases.get(name, set())
            | self.text_terms.get(name, set())
        )
        out = set()
        for t in base:
            for v in (t, t.replace("'", "")):
                out.add(v)
                if len(v) > 4:
                    out.add(v[:-1] if v.endswith("s") else v + "s")
        return out

    def gene_terms(self, symbol: str) -> set[str]:
        """
        Terms that count as the text naming the gene: the symbol, the curated
        aliases (multi-gene addendum rows included, as in the scan: "H3.3"
        for H3-3A), and any alias the pipeline itself resolves to this symbol.
        """
        curated = set(self.curated.get(symbol, ())) | set(self.curated_groups.get(symbol, ()))
        return (
            {symbol}
            | curated
            | {a for a in self.gene_aliases.get(symbol, ()) if rv.canonical_gene(a) == symbol}
        )

    def weak_gene_terms(self, symbol: str) -> set[str]:
        """
        Other NCBI aliases (MLL for KMT2A, N-MYC for MYCN, but also ALL and CML
        for BCR, ROS for ROS1). Shown to the curator, never counted as support.
        """
        return {a for a in self.gene_aliases.get(symbol, ()) if len(a) > 2} - self.gene_terms(
            symbol
        )

    def ancestors(self, name: str) -> list[str]:
        out, n = [], self.parent.get(name)
        while n:
            out.append(n)
            n = self.parent.get(n)
        return out
