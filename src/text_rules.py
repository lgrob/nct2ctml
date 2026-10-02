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


# --- Gene criteria: encoding fixes and scope (gene audit, 2026-10-02) -------
#
# doc/runs/2026-10-02-3.4-gene-audit.md read the gene criteria of 80 published
# trials: 30 lost eligible patients. Two groups are handled here.
# - fix_gene_encodings rewrites three encodings that are wrong whatever the
#   trial means: a required ITD written as a structural variant, a "V600E" exclusion
#   widened to every BRAF mutation, and a medulloblastoma subgroup written as
#   a gene.
# - gene_scope_suspect finds a gene required of every patient where the text
#   gives it for one cohort, or as one route beside routes that need no
#   alteration. It cannot tell what the tree should be, so it routes the
#   trial to review.

_ITD = r"[\s:-]*(?:ITD|internal\s+tandem\s+duplications?)(?![A-Za-z])"
_FUSION_WORDS = r"[\s:-]*(?:fusions?|rearrange\w*|translocations?)"
# A change written after the gene: "BRAF V600E", "BRAFV600E", "BRAF p.V600".
_CHANGE_AFTER = re.compile(r"[\s-]*(?:p\.)?([A-Z]\d{1,4}(?:[A-Z]|\*)?)(?![A-Za-z0-9])")
# A mention that names a drug class, not the alteration: "prior BRAF inhibitor".
_DRUG_AFTER = re.compile(
    r"[\s/-]*(?:and\s+MEK\s+)?(?:inhibitors?|targeted|-?directed|therap)", re.I
)
# Molecular subgroups written with a gene's name. SHH-activated medulloblastoma
# is driven by PTCH1, SUFU or SMO: an SHH variant is almost never there, so a
# criterion on the SHH gene matches nobody (2024-517133-40-00, COGNITO-MB) or
# excludes nobody (NCT06193759).
_SUBGROUP_NAMES = {
    "SHH": re.compile(
        r"SHH[\s-]*(?:activated|subgroups?|subtypes?|groups?|types?|MB\b|medulloblastoma|TP53|"
        r"pathway|driven|\+|positive)",
        re.I,
    ),
}


def _negated(g: dict) -> bool:
    return any(
        str(g.get(k, "")).startswith("!")
        for k in ("variant_category", "cnv_call", "protein_change")
    )


def _unescape(text: str | None) -> str:
    """ClinicalTrials.gov markdown escapes: "\\[", "\\>", "\\*"."""
    return re.sub(r"\\([\[\]<>*_-])", r"\1", text or "")


def _gene_lists(node, parent_key=None):
    """Yield (list, parent_key) for every list in a match tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _gene_lists(v, k)
    elif isinstance(node, list):
        yield node, parent_key
        for v in node:
            yield from _gene_lists(v, parent_key)


def _says_itd(gene: str, text: str, ref: "Reference") -> bool:
    terms = [t for t in ref.gene_terms(gene) if len(t) >= 3] + (["FLT"] if gene == "FLT3" else [])
    names = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    if not names:
        return False
    if re.search(rf"(?<![A-Za-z0-9])(?:{names}){_FUSION_WORDS}", text, re.I):
        return False
    if re.search(rf"(?<![A-Za-z0-9])(?:{names}){_ITD}", text, re.I):
        return True
    # In leukaemia texts a bare "ITD" is FLT3's.
    return gene == "FLT3" and bool(re.search(r"(?<![A-Za-z])ITD(?![A-Za-z])", text))


def _itd_as_mutation(tree, text, ref) -> list[str]:
    """
    An internal tandem duplication is an in-frame insertion: variant callers
    and MatchMiner's genomic records file it as a mutation, not a structural
    variant. "FLT3-ITD" written as a Structural Variation therefore matches no
    ITD patient (NCT06262438, every patient lost), and an ITD exclusion
    written that way excludes nobody (2025-522279-27-00).

    The structural-variant criterion is kept, since a laboratory may still
    report the ITD that way, and a mutation criterion is added beside it as
    an alternative. Exclusions are left as they are: making an ITD exclusion
    bite would lose patients wherever the exclusion belongs to one
    randomisation or cohort only (2023-504999-25-00, CHIP-AML22), and
    exclusion genes get no role check. A wrong exclusion that excludes nobody
    over-matches; one that bites loses patients.
    """
    import copy

    notes = []
    for lst, parent in list(_gene_lists(tree)):
        i = 0
        while i < len(lst):
            n = lst[i]
            g = n.get("genomic") if isinstance(n, dict) else None
            vc = str((g or {}).get("variant_category", ""))
            if (
                not isinstance(g, dict)
                or vc != "Structural Variation"
                or g.get("fusion_partner")
                or not _says_itd(g.get("hugo_symbol", ""), text, ref)
            ):
                i += 1
                continue
            twin = copy.deepcopy(n)
            twin["genomic"].pop("fusion_partner_unverified", None)
            twin["genomic"]["variant_category"] = "Mutation"
            if parent == "or":
                if twin not in lst:
                    lst.insert(i + 1, twin)
                    i += 1
            else:
                lst[i] = {"or": [n, twin]}
            notes.append(
                f"{g['hugo_symbol']} ITD: mutation criterion added beside the structural variant"
            )
            i += 1
    return notes


def _exclusion_protein_change(tree, text, ref) -> list[str]:
    """
    An exclusion on a whole gene where the text names one change: "LGG
    without a BRAFV600E mutation" published as BRAF !Mutation excludes every
    BRAF-mutant glioma (NCT04166409, NCT05099003). When every mention of the
    gene in the eligibility text carries the same protein change, the
    exclusion gets that change. A mention without one ("BRAF mutation") or
    two different changes leave it as it is. Mentions of a drug class ("prior
    BRAF inhibitor") are not mentions of the alteration.
    """
    import utils.protein_change as protein_change

    notes = []
    for lst, _ in list(_gene_lists(tree)):
        for n in list(lst):
            g = n.get("genomic") if isinstance(n, dict) else None
            if (
                not isinstance(g, dict)
                or str(g.get("variant_category")) not in ("!Mutation", "!Any Variation")
                or g.get("protein_change")
                or g.get("wildcard_protein_change")
            ):
                continue
            gene = g.get("hugo_symbol", "")
            changes, plain = set(), False
            for _, e, _ in find_mentions(text, ref.gene_terms(gene), gene=gene):
                right = text[e : e + 30]
                if _DRUG_AFTER.match(right):
                    continue
                m = _CHANGE_AFTER.match(right)
                if m:
                    changes.add(m.group(1))
                else:
                    plain = True
            if plain or len(changes) != 1:
                continue
            stated = changes.pop()
            if not protein_change.normalise(gene, stated).verified:
                continue
            g["variant_category"] = "!Mutation"
            g["protein_change"] = f"p.{stated}"
            notes.append(f"{gene} exclusion narrowed to p.{stated}, the only change the text names")
            # The model sometimes wrote both; keep one.
            twins = [x for x in lst if x == n]
            for extra in twins[1:]:
                lst.remove(extra)
    return notes


def _drop_subgroup_genes(tree, text) -> list[str]:
    """
    Remove criteria on a gene whose every mention in the text is a subgroup
    name ("SHH-activated medulloblastoma", "SHH subtype"), with the AND/OR
    nodes they leave empty. A text that also names the gene as an alteration
    ("SHH mutation") keeps it.
    """
    notes = []
    for gene, subgroup in _SUBGROUP_NAMES.items():
        mentions = list(re.finditer(rf"(?<![A-Za-z0-9]){gene}(?![a-z0-9])", text))
        if not mentions or any(not subgroup.match(text, m.start()) for m in mentions):
            continue
        removed = 0
        for lst, _ in list(_gene_lists(tree)):
            keep = [
                n
                for n in lst
                if not (isinstance(n, dict) and (n.get("genomic") or {}).get("hugo_symbol") == gene)
            ]
            removed += len(lst) - len(keep)
            lst[:] = keep
        if removed:
            _prune_empty(tree)
            notes.append(
                f"{gene} removed: the text names the {gene} subgroup, not an {gene} alteration"
            )
    return notes


def _prune_empty(node):
    """Drop {"and": []} / {"or": []} left behind, bottom up."""
    if isinstance(node, dict):
        for v in node.values():
            _prune_empty(v)
    elif isinstance(node, list):
        for v in node:
            _prune_empty(v)
        node[:] = [
            n
            for n in node
            if not (isinstance(n, dict) and set(n) <= {"and", "or"} and not any(n.values()))
        ]


def fix_gene_encodings(
    ctml: dict | None, inclusion: str | None, exclusion: str | None, ref: "Reference | None" = None
) -> list[str]:
    """
    Apply the three encoding rules to the match tree in place and return a
    note for each change. Deterministic, no model call.
    """
    if not isinstance(ctml, dict) or not ctml.get("treatment_list"):
        return []
    ref = ref or _shared_reference()
    text = _unescape(inclusion) + "\n" + _unescape(exclusion)
    tree = ctml["treatment_list"]
    notes = (
        _itd_as_mutation(tree, text, ref)
        + _exclusion_protein_change(tree, text, ref)
        + _drop_subgroup_genes(tree, text)
    )
    return list(dict.fromkeys(notes))


# Cues for gene_scope_suspect, measured on the gene audit's 80 trials.
_DX_WORD = re.compile(
    r"tumou?r|cancer|carcinoma|sarcoma|leuka?emia|lymphoma|glioma|malignan|blastoma|myeloma|\bALL\b",
    re.I,
)
_ROUTE_WORD = re.compile(
    r"tumou?rs?|cancers?|carcinoma|sarcoma|leuka?emia|lymphoma|glioma|neoplasm|malignan|blastoma|"
    r"myeloma|\bALL\b|\bAML\b|\bMDS\b|\bNHL\b|\bCLL\b|relapse|refractory|MRD|disease",
    re.I,
)
# Segments about how or where a test is done, not about who is eligible.
_NOT_A_ROUTE = re.compile(
    r"measurable|evaluable|RECIST|tumou?r (?:tissue|sample|specimen)|plasma|sequencing|NGS|"
    r"laboratory|\btest",
    re.I,
)
_LIST_CUE = re.compile(
    r"one of the following|any of the following|\beither\b|(?<![A-Za-z])OR(?![A-Za-z])", re.I
)
_SECTION_HEADER = re.compile(
    r"(?im)^[\s*•\-\d.()]*((?:phase\s*(?:I{1,3}|[123])[ab]?|part\s+[A-Z0-9]+|stratum\s+\w+|"
    r"arm\s+[A-Z0-9]+|cohorts?\s+[\w,\s-]{1,30}?|dose[- ](?:escalation|expansion)(?:\s+cohort)?)"
    r"(?:\s+only)?)\s*(?::|\n|$)"
)
_COHORT_SCOPE = re.compile(
    r"\b(?:for|in)\s+(?:the\s+)?[\w-]+\s+(?:cohort|arm|stratum|part)\b|"
    r"\bcohort[\w\s,-]{0,25}\bonly\b|"
    r"\bno\s+(?:\w+\s+)?(?:mutation|alteration)s?\s+(?:is\s+)?(?:needed|required)",
    re.I,
)


def _step_required_genes(ctml: dict) -> set[str]:
    """Genes required at step level: an arm's own criteria are already scoped."""
    found = set()
    for step in (ctml.get("treatment_list") or {}).get("step", []) or []:
        for g in _genomic_nodes(step.get("match")):
            if g.get("hugo_symbol") and not _negated(g):
                found.add(g["hugo_symbol"])
    return found


def _criterion_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """The top-level criterion holding [start, end): lines up to the next unindented one."""
    starts = [m.start() for m in re.finditer(r"\n(?=\S)", text[:start])]
    nxt = re.search(r"\n(?=\S)", text[end:])
    return (starts[-1] if starts else 0), (end + nxt.start() if nxt else len(text))


def _segments(text: str) -> list[str]:
    parts = re.split(
        r"\n+|\s[•*]\s|;|\s-\s|\s(?=\d{1,2}\.\s)|\s(?=[a-h][.)]\s)|\s(?:or|OR)\s", text
    )
    return [p for p in parts if len(p.strip()) >= 20]


def gene_scope_suspect(
    ctml: dict | None, inclusion: str | None, ref: "Reference | None" = None
) -> dict[str, str]:
    """
    Genes the match tree requires of every patient although the inclusion
    text gives them for one cohort, or as one route among others. Returns
    {gene: reason and fragment}. Deterministic, no model call.

    A mention of the gene counts as scoped when:
    - the gene is named both positive and negative ("FOXO1 fusion negative
      ... FOXO1 fusion positive", NCT07466316): a stratifier;
    - its sentence limits it to a cohort ("for primary cohort; no mutation
      needed for exploratory cohort", NCT06411821);
    - it sits under a "... only" header ("Dose Expansion Cohort Only",
      NCT05372640), or under a phase/cohort/arm header while another such
      section names a population and no required gene (NCT04901702);
    - its criterion opens alternatives ("one of the following", "either",
      "OR") and one alternative names a population or disease state and no
      gene (2024-515174-27-00, 2024-511336-28-00, NCT06961669);
    - a stand-alone OR line joins its criterion to one that names a
      population and no gene (NCT03150576, TNBC OR gBRCA);
    - its criterion lists labelled alternatives and a label naming a disease
      has no gene ("ETP-ALL: ... T-ALL with myeloid mutations: FLT3, ...",
      NCT07159620).

    Measured on the gene audit's 80 trials: 9 of its 10 scope losses found,
    1 of 43 correct trials flagged (a phase 1 that does not require RET at
    first, which the audit had missed). On all 982 published trials of the
    replayed corpus it flags 24; of the 13 outside the audit, 10 were real.
    """
    if not isinstance(ctml, dict):
        return {}
    genes = _step_required_genes(ctml)
    if not genes:
        return {}
    ref = ref or _shared_reference()
    text = _unescape(inclusion)
    mentions = {}
    for g in genes:
        mentions[g] = find_mentions(
            text, [t for t in ref.gene_terms(g) if len(t) >= 3 or t == g], gene=g
        )
        if not mentions[g]:  # "NUT carcinoma" for NUTM1
            mentions[g] = find_mentions(
                text, [t for t in ref.weak_gene_terms(g) if len(t) >= 3], gene=g
            )
    spans = [s for g in genes for s, _, _ in mentions[g]]

    def names_gene(a, b):
        return any(a <= s < b for s in spans)

    headers = list(_SECTION_HEADER.finditer(text))
    out: dict[str, str] = {}
    for gene in sorted(genes):
        for s, e, _ in mentions[gene]:
            reason = _scope_reason(text, s, e, headers, names_gene)
            if reason:
                out[gene] = f"{reason}: " + " ".join(text[max(0, s - 80) : e + 60].split())
                break
    return out


def _scope_reason(text, s, e, headers, names_gene) -> str:
    said = re.escape(text[s:e])
    qualifier = r"[\s-]*(?:fusion|mutation|rearrangement|status)?[\s-]*"
    if re.search(rf"{said}{qualifier}(?:negative|\(FN\))", text, re.I) and re.search(
        rf"{said}{qualifier}(?:positive|\(FP\))", text, re.I
    ):
        return "named both positive and negative"

    a = max(text.rfind(c, 0, s) for c in (".", "\n", ";")) + 1
    ends = [x for x in (text.find(c, e) for c in (". ", ".\n", "\n", ";")) if x >= 0]
    if _COHORT_SCOPE.search(text[a : min(ends or [len(text)])]):
        return "limited to a cohort in its sentence"

    above = [h for h in headers if h.start() < s]
    if above:
        own = above[-1]
        if "only" in own.group(1).lower():
            return f"under the header '{own.group(1).strip()}'"
        bounds = [h.start() for h in headers] + [len(text)]
        for i, h in enumerate(headers):
            if h.start() != own.start() and not names_gene(h.end(), bounds[i + 1]):
                if _DX_WORD.search(text[h.end() : bounds[i + 1]]):
                    return f"section '{h.group(1).strip()}' names a population and no required gene"

    ia, ib = _criterion_bounds(text, s, e)
    item = text[ia:ib]
    cues = [
        m
        for m in _LIST_CUE.finditer(item)
        if ia + m.start() < s
        and (m.group(0) == "OR" or m.group(0).lower() != "or")
        # "either bone or soft tissue": two words, not two routes
        and not (
            m.group(0).lower() == "either"
            and re.match(r"either\s.{0,40}?\sor\s", item[m.start() :], re.I | re.S)
        )
    ]
    if cues:
        for seg in _segments(item[cues[0].start() :]):
            off = text.find(seg, ia)
            if off >= 0 and not names_gene(off, off + len(seg)):
                if _ROUTE_WORD.search(seg) and not _NOT_A_ROUTE.search(seg):
                    return f"an alternative names no gene ('{' '.join(seg.split())[:70]}')"

    before = re.search(r"((?:^|\n)\S[^\n]*(?:\n[ \t]+[^\n]*)*)\n\s*OR\s*\n\s*$", text[: ia + 1])
    if (
        before
        and not names_gene(before.start(1), before.end(1))
        and _DX_WORD.search(before.group(1))
    ):
        return f"an OR joins a criterion that names no gene ('{' '.join(before.group(1).split())[:70]}')"
    after = re.match(r"\s*\n\s*OR\s*\n+(\S[^\n]*(?:\n[ \t]+[^\n]*)*)", text[ib:])
    if (
        after
        and not names_gene(ib + after.start(1), ib + after.end(1))
        and _DX_WORD.search(after.group(1))
    ):
        return f"an OR joins a criterion that names no gene ('{' '.join(after.group(1).split())[:70]}')"

    labels = list(re.finditer(r"\n[ \t]+([A-Za-z][\w /+-]{1,40}):\s", item))
    if len(labels) >= 2:
        bounds = [m.start() for m in labels] + [len(item)]
        for i, m in enumerate(labels):
            if not names_gene(ia + m.start(), ia + bounds[i + 1]) and _DX_WORD.search(m.group(1)):
                return f"the labelled alternative '{m.group(1)}' names no gene"
    return ""


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
