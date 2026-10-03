"""
What the eligibility text names that the CTML does not carry: the direction
the review sheet did not show.

The sheet lists every published criterion with the passage it came from. A
curator also has to find the opposite: a population the text names that is
not published, an exclusion the text states that the published diagnoses
still admit, a gene stated with an alteration that is in no criterion, and
the ages the text states beside the published bounds. Those were the
commonest errors in the third audit (doc/runs/2026-10-03-3.4-audit-3.md:
24 of 34 losing trials had a named population missing; exclusions not
written were the largest over-match cause).

Deterministic: Oncotree names, their aliases and text terms, and the text
floor's group rows (ref/diagnosis_groups.tsv), matched as the pipeline
matches them. Coverage is judged on the patient codes each side reaches
(utils.build_trial_index.diagnosis_population), so a published parent covers
its children. Everything here is a hint for the curator, never an edit.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import src.text_rules as text_rules
import utils.reference_validation as rv

WILDCARDS = frozenset({"_SOLID_", "_LIQUID_"})
# A mention right after one of these words is probably an exclusion written
# inside the inclusion text ("solid tumours other than osteosarcoma").
_NEGATION_BEFORE = re.compile(
    r"(?:excluding|except(?: for)?|other than|apart from|without|non-)\W{0,3}(?:\w+\W+){0,1}$",
    re.I,
)
_ALTERATION_AFTER = re.compile(
    r"^[\s:-]*(?:gene\s+)?(?:mutations?|mutated|mutant|fusions?|rearrange\w*|"
    r"amplifi\w*|alterations?|altered|deletions?|translocations?|positive|"
    r"-?ITD|V\d{2,4}[A-Z]?)\b",
    re.I,
)
_AGE_SENTENCE = re.compile(
    r"[^.\n;]*(?:\bage[ds]?\b|years? old|years? of age|\byrs?\b|months? of age)[^.\n;]*", re.I
)


@dataclass
class Gap:
    kind: str  # "named, not published" | "excluded in text, still admitted" | "gene not used"
    term: str  # the words in the text
    where: str  # inclusion | exclusion | title | conditions
    targets: list = field(default_factory=list)  # Oncotree terms (or gene) the words mean
    status: str = ""  # "none of its codes published", "3 of 8 codes published", ...
    snippet: str = ""
    span: tuple = ()  # (start, end) in that section's text


@lru_cache(maxsize=1)
def _diagnosis_matchers():
    """
    [(compiled pattern, term, targets)] for every way a text names a
    diagnosis: each Oncotree name with its aliases and text terms, and each
    text-floor group row. Compiled once per process (several thousand terms).
    """
    ref = text_rules._shared_reference()
    terms: dict[str, set] = {}
    # Organ-system roots ("Bone", "Liver", "Other") are ordinary words in an
    # eligibility text, not populations.
    for name in ref.names - set(ref.level1):
        for t in ref.dx_terms(name):
            if len(t) >= 3:
                terms.setdefault(t, set()).add(name)
    for term, _regex, _guard, targets in rv._diagnosis_groups():
        if term and targets:
            terms.setdefault(term, set()).update(targets)
    out = []
    for t in sorted(terms, key=len, reverse=True):
        if len(t) <= 4 and t.isupper():
            pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])")
        else:
            pattern = re.compile(text_rules._term_pattern(t), re.I)
        out.append((pattern, t, sorted(terms[t])))
    return out


def diagnosis_mentions(text: str):
    """[(start, end, term, targets)], longest term first, no overlaps."""
    hits = []
    for pattern, term, targets in _diagnosis_matchers():
        for m in pattern.finditer(text or ""):
            if not any(s < m.end() and m.start() < e for s, e, _, _ in hits):
                hits.append((m.start(), m.end(), term, targets))
    return sorted(hits)


def _published(ctml):
    """(admitted diagnoses, excluded diagnoses) anywhere in the match tree."""
    dx = text_rules.collect(ctml)["diagnoses"]
    return [d for d in dx if not d.startswith("!")], [d[1:] for d in dx if d.startswith("!")]


def _snippet(text, s, e, width=90):
    a, b = max(0, s - width), min(len(text), e + width)
    return ("..." if a else "") + " ".join(text[a:b].split()) + ("..." if b < len(text) else "")


def gaps(ctml: dict, sections: dict[str, str]) -> list[Gap]:
    """
    The gaps between the text and the CTML. `sections` maps inclusion,
    exclusion, title and conditions to their text.
    """
    from utils.build_trial_index import diagnosis_population

    admitted, excluded = _published(ctml)
    reached = diagnosis_population(admitted) if admitted else set()
    shut = diagnosis_population(excluded) if excluded else set()
    out: list[Gap] = []
    seen = set()
    for where in ("title", "conditions", "inclusion", "exclusion"):
        text = sections.get(where) or ""
        for s, e, term, targets in diagnosis_mentions(text):
            if set(targets) & WILDCARDS and where == "exclusion":
                continue
            codes = diagnosis_population(targets)
            if not codes:
                continue
            negated = where == "inclusion" and _NEGATION_BEFORE.search(text[max(0, s - 40) : s])
            if where == "exclusion" or negated:
                still = (codes & reached) - shut
                if still and (term.lower(), "x") not in seen:
                    seen.add((term.lower(), "x"))
                    out.append(
                        Gap(
                            "excluded in text, still admitted",
                            text[s:e],
                            where,
                            targets,
                            f"{len(still)} of {len(codes)} codes still admitted",
                            _snippet(text, s, e),
                            (s, e),
                        )
                    )
                continue
            missing = codes - reached
            if missing and (term.lower(), "n") not in seen:
                seen.add((term.lower(), "n"))
                out.append(
                    Gap(
                        "named, not published",
                        text[s:e],
                        where,
                        targets,
                        "none of its codes published"
                        if missing == codes
                        else f"{len(codes) - len(missing)} of {len(codes)} codes published",
                        _snippet(text, s, e),
                        (s, e),
                    )
                )
    out += _gene_gaps(ctml, sections)
    return out


def _gene_gaps(ctml, sections):
    """Genes the text states with an alteration that are in no criterion and not kept out."""
    used = {g.get("hugo_symbol") for g in text_rules.collect(ctml)["genomic"]}
    kept_out = {
        part.strip().split(" ")[0]
        for part in str(ctml.get("gene_role_dropped") or "").split(";")
        if part.strip()
    }
    out, seen = [], set()
    for where in ("inclusion", "exclusion"):
        text = sections.get(where) or ""
        for m in re.finditer(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9-]{1,9})(?![a-z])", text):
            if not _ALTERATION_AFTER.match(text[m.end() : m.end() + 30]):
                continue
            symbol = rv.canonical_gene(m.group(1))
            if not symbol or symbol in used or symbol in kept_out or symbol in seen:
                continue
            seen.add(symbol)
            out.append(
                Gap(
                    "gene not used",
                    m.group(1),
                    where,
                    [symbol],
                    "in no genomic criterion",
                    _snippet(text, m.start(), m.end()),
                    (m.start(), m.end()),
                )
            )
    return out


def stated_ages(sections: dict[str, str]) -> list[str]:
    """The sentences of the inclusion text that state an age."""
    return [
        " ".join(m.group(0).split())
        for m in _AGE_SENTENCE.finditer(sections.get("inclusion") or "")
        if re.search(r"\d", m.group(0))
    ][:6]
