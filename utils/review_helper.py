"""
Review helper: put the evidence for every flag next to the flag, and make
accepting a reviewed trial a checked, logged step.

A trial lands in ctml/needs-review/ with one or more flags written beside
the item they concern (gene_unsupported, diagnosis_off_list,
protein_change_unverified, fusion_partner_unverified) or with no diagnosis
at all. Deciding each flag means finding the matching sentence in the
eligibility text. This module does that lookup deterministically, with the
same reference data the mapper uses, and writes one HTML sheet per trial:

- every flag, what it means, the text passages that mention the item
  (aliases, translocation notation and British spelling included), and the
  edit that resolves it;
- every diagnosis marked "named in text", "parent named in text" or "not
  named". On the stage-2 runs 82% of named diagnoses were correct, and most
  correct diagnoses are subtypes of a named parent, so the unnamed ones
  are where to look first;
- protein changes with the residue the reference protein actually carries;
- the eligibility text with every mention highlighted.

The sheet only reads. The curator edits the YAML in ctml/needs-review/ and
then runs `accept`, which refuses a file that still carries a flag, has no
diagnosis, names a gene or diagnosis that is not in the reference data, or
has a protein change that fails its reference check. On success it stamps
curated_on, moves the file to ctml/reviewed/ (the index layer that wins),
and appends one line to ctml/review_log.tsv: who, when, which flags were
resolved, and the file's SHA-256.

    python -m utils.review_helper queue                   # the queue, with reasons
    python -m utils.review_helper sheets                  # HTML sheets for the whole queue
    python -m utils.review_helper sheets NCT05843253      # ... or for named trials
    python -m utils.review_helper audit --n 60            # random mapped trials for roadmap 3.4
    python -m utils.review_helper check NCT05843253       # what accept would refuse, without moving
    python -m utils.review_helper accept NCT05843253 --reviewer lgrob [--note "..."]
    python -m utils.review_helper exclude NCT05843253 --reviewer lgrob --reason "adult-only, not oncology"

Sheets go to review_sheets/ (git-ignored); open review_sheets/index.html.
"""

import argparse
import csv
import datetime
import hashlib
import html
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field

import yaml
from loguru import logger

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import utils.gene_mentions as gene_mentions
import utils.protein_change as protein_change
import utils.reference_validation as rv
import utils.translocations as translocations
from utils.oncotree import get_lineage

MAPPED_DIR = "cache/ctml"
REVIEW_DIR = "ctml/needs-review"
REVIEWED_DIR = "ctml/reviewed"
LOG_FILE = "ctml/review_log.tsv"
SHEET_DIR = "review_sheets"
LOG_COLUMNS = ["date", "trial_id", "reviewer", "from_layer", "flags_resolved", "sha256", "note"]

# Keys the mapper writes to mark an item for review. `accept` refuses a file
# that still holds any of them: deleting the key is how a curator confirms
# the item, deleting the item is how they reject it.
FLAG_KEYS = ("gene_unsupported", "diagnosis_off_list", "diagnosis_excluded", "genomic_contradiction",
             "protein_change_unverified",
             "protein_change_check", "fusion_partner_unverified")

WILDCARDS = {"_SOLID_", "_LIQUID_"}

# British/American variants, applied per word when searching for a diagnosis.
_SPELLING = [("leukemia", "leuka?emia"), ("tumor", "tumou?r"), ("hemato", "ha?emato"),
             ("esophag", "o?esophag"), ("anemia", "ana?emia"), ("hemangio", "ha?emangio")]

ADVICE = {
    "no_diagnosis": "No diagnosis: as it stands the trial matches every patient. Add "
                    "oncotree_primary_diagnosis entries, or _SOLID_ / _LIQUID_ for a basket trial.",
    "gene_unsupported": "The model returned a gene the text scan did not find. If the text requires it, "
                        "delete the `gene_unsupported:` line; if not, delete the whole genomic criterion.",
    "diagnosis_off_list": "A diagnosis was answered outside the candidate list the model was offered. "
                          "Keep or remove that diagnosis in the match tree, then delete the top-level "
                          "`diagnosis_off_list:` line.",
    "diagnosis_excluded": "This diagnosis is named in the exclusion criteria and nowhere in the inclusion "
                          "criteria, title or conditions: the trial probably excludes it. Delete it from the "
                          "match tree, or, when a broader diagnosis the trial enrols contains it, add it as "
                          "`oncotree_primary_diagnosis: '!Name'` (quoted) beside that diagnosis. Then delete "
                          "the top-level `diagnosis_excluded:` line.",
    "genomic_contradiction": "The match tree requires and forbids the same gene under one AND, so it matches "
                             "nobody. Often an exclusion written for the whole gene ('!Any Variation') where the "
                             "text excludes one variant, or a gene also required as a fusion partner. Narrow or "
                             "remove the exclusion, then delete the top-level `genomic_contradiction:` line.",
    "protein_change_unverified": "The stated protein change does not match the reference protein. Write the "
                                 "correct change as `protein_change:` (it is re-checked), or drop it; then "
                                 "delete `protein_change_unverified:` and `protein_change_check:`.",
    "fusion_partner_unverified": "The fusion partner is not an official gene symbol. Replace the line with "
                                 "`fusion_partner: <symbol>` or delete it.",
}


# --------------------------------------------------------------------- data

@dataclass
class Item:
    kind: str                  # diagnosis | gene | age | protein | partner | no_diagnosis
    value: str
    flag: str = ""             # a FLAG_KEYS entry, or "no_diagnosis"
    side: str = ""             # inclusion | exclusion (genomic include flag)
    evidence: list = field(default_factory=list)   # [(section, snippet html)]
    note: str = ""


def _layer_of(trial_id):
    for d, layer in ((REVIEW_DIR, "needs_review"), (MAPPED_DIR, "mapped"), (REVIEWED_DIR, "reviewed")):
        p = os.path.join(d, f"{trial_id}.yaml")
        if os.path.exists(p):
            return p, layer
    raise SystemExit(f"{trial_id}: not found in {REVIEW_DIR}, {MAPPED_DIR} or {REVIEWED_DIR}")


def eligibility_text(trial_id):
    """(inclusion, exclusion) from the cached registry record, as the mapper split it."""
    if trial_id.startswith("NCT"):
        import src.clinical_trials_gov as reg
        path = f"cache/nct/{trial_id}.json"
    else:
        import src.ctis as reg
        path = f"cache/ctis/{trial_id}.json"
    if not os.path.exists(path):
        return "", "", {}
    record = json.load(open(path))
    inc, exc = reg.split_inclusion_exclusion_criteria(record)
    return inc or "", exc or "", record


def registry_ages(record):
    elig = (record.get("protocolSection") or {}).get("eligibilityModule") or {}
    return elig.get("minimumAge", ""), elig.get("maximumAge", "")


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
        for d in (dx if isinstance(dx, list) else [dx]):
            if d:
                out["diagnoses"].append(str(d))   # "!Name" kept: an excluded diagnosis
        if clinical.get("age_numerical"):
            out["ages"].append(str(clinical["age_numerical"]))
    genomic = node.get("genomic")
    if isinstance(genomic, dict):
        out["genomic"].append(genomic)
    for k, v in node.items():
        if k not in ("clinical", "genomic"):
            _walk(v, out, include)


def collect(ctml):
    out = {"diagnoses": [], "ages": [], "genomic": []}
    _walk(ctml.get("treatment_list", ctml), out)
    return out


# ----------------------------------------------------------------- evidence

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


def _as_set(value):
    """A flag value as a set of names: a list, or a string joined with '; '."""
    if isinstance(value, list):
        return {str(v) for v in value}
    return {v.strip() for v in str(value).split(";") if v.strip()} if value else set()


def diagnoses_only_in_exclusions(diagnoses, inclusion, exclusion, context=(), ref=None):
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


_SHARED = []


def _shared_reference():
    """One Reference per process, so the mapper does not reload it per trial."""
    if not _SHARED:
        _SHARED.append(Reference())
    return _SHARED[0]


def flag_exclusions(apply=False):
    """
    Apply the diagnosis_excluded check to CTML already written (mapped and
    review layers; ctml/reviewed is never touched). Returns
    [(trial_id, layer, [diagnoses])]. With apply=True, the key is added and a
    mapped trial is moved to the review queue, as the mapper now does.
    """
    ref = _shared_reference()
    import utils.oncology_scope as scope
    out_of_scope = set(scope.load_report()) | {t for t, (dec, _) in scope.load_overrides().items() if dec == "skip"}
    found = []
    for d, layer in ((MAPPED_DIR, "mapped"), (REVIEW_DIR, "needs_review")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".yaml"):
                continue
            t = f[:-5]
            if t in out_of_scope:
                continue    # not in the index; no point queueing it
            if os.path.exists(os.path.join(REVIEWED_DIR, f)):
                continue    # a curated copy exists and is what the index publishes
            path = os.path.join(d, f)
            raw = open(path).read()
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict) or ctml.get("diagnosis_excluded"):
                continue
            try:
                inc, exc, data = eligibility_text(t)
            except (OSError, ValueError, KeyError):
                continue
            context = [str(ctml.get("long_title") or ""), str(ctml.get("short_title") or "")] + _conditions(t, data)
            hit = diagnoses_only_in_exclusions(collect(ctml)["diagnoses"], inc, exc, context, ref)
            if not hit:
                continue
            found.append((t, layer, hit))
            if apply:
                target = os.path.join(REVIEW_DIR, f)
                if layer == "mapped" and os.path.exists(target):
                    continue    # a review copy exists and wins; leave both for the curator
                text = raw.rstrip("\n") + "\n" + yaml.safe_dump({"diagnosis_excluded": "; ".join(hit)},
                                                                 allow_unicode=True, width=1000)
                os.makedirs(REVIEW_DIR, exist_ok=True)
                with open(target, "w") as fh:
                    fh.write(text)
                if layer == "mapped":
                    os.remove(path)
    return found


def _genomic_nodes(node):
    if isinstance(node, dict):
        if isinstance(node.get("genomic"), dict):
            yield node["genomic"]
        for v in node.values():
            yield from _genomic_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _genomic_nodes(v)


def flag_unsupported_genes(apply=False):
    """
    Re-run the mapper's unsupported-gene check (match_criteria_mapper.
    _flag_unsupported_genes, same scan and support rules) on CTML already
    written, against the trial's whole inclusion+exclusion text. Added
    2026-09-27 after 15 short aliases were blocked: criteria the text
    supported only through such a word ("ICF" -> DNMT3B) had passed. An
    expression-only gene (src/trial_config.expression_only_genes) in a
    genomic block is flagged too.

    Mapped and review layers only; ctml/reviewed is never touched, nor are
    out-of-scope trials. Returns [(trial_id, layer, [genes], action)].
    With apply=True the flag is written beside the gene as the mapper writes
    it, and a mapped trial moves to the review queue. A file with curator
    comments is never rewritten (yaml would drop them); it is reported as
    "edited: check by hand".
    """
    import copy
    import src.match_criteria_mapper as mcm
    import src.trial_criteria_to_genes as tcg
    from src import trial_config
    import utils.oncology_scope as scope
    expression_only = set(getattr(trial_config, "expression_only_genes", []))
    syn = rv.gene_synonym_mapping()
    out_of_scope = set(scope.load_report()) | {t for t, (dec, _) in scope.load_overrides().items() if dec == "skip"}
    found = []
    for d, layer in ((MAPPED_DIR, "mapped"), (REVIEW_DIR, "needs_review")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".yaml"):
                continue
            t = f[:-5]
            if t in out_of_scope or os.path.exists(os.path.join(REVIEWED_DIR, f)):
                continue
            path = os.path.join(d, f)
            raw = open(path).read()
            ctml = yaml.safe_load(raw)
            if not isinstance(ctml, dict):
                continue
            try:
                inc, exc, data = eligibility_text(t)
            except (OSError, ValueError, KeyError):
                continue
            # The mapper's arm text includes arm descriptions and the title
            # (NCT06265545 names IDH1/FLT3 only in its arms); registry markdown
            # escapes brackets ("\\[MLL\\]", NCT02727803).
            text = "\n".join([inc, exc] + _arm_and_title_text(t, data)).replace("\\[", "[").replace("\\]", "]")
            scanned = tcg.TrialCriteriaToGenes(trial_criteria=text, synonym_to_symbol=syn).extract_official_gene_symbols()
            new = []
            nodes = [g for g in _genomic_nodes(ctml.get("treatment_list")) if not g.get("gene_unsupported")]
            for g in nodes:
                probe = [{"genomic": copy.deepcopy(g)}]
                mcm._flag_unsupported_genes(probe, scanned, text, t)
                missing = probe[0]["genomic"].get("gene_unsupported")
                expr = [x for x in (g.get("hugo_symbol"), g.get("fusion_partner")) if x in expression_only]
                if expr:
                    missing = ", ".join(filter(None, [missing] + [f"{x} (expression-only)" for x in expr]))
                if missing:
                    new.append((g, missing))
            if not new:
                continue
            edited = bool(re.search(r"^\s*#", raw, re.M))
            action = "edited: check by hand" if edited else ("moved to review" if layer == "mapped" else "flagged")
            found.append((t, layer, [m for _, m in new], action))
            if apply and not edited:
                target = os.path.join(REVIEW_DIR, f)
                if layer == "mapped" and os.path.exists(target):
                    continue
                for g, missing in new:
                    g["gene_unsupported"] = missing
                os.makedirs(REVIEW_DIR, exist_ok=True)
                with open(target, "w") as fh:
                    fh.write(yaml.dump(ctml, sort_keys=False))
                if layer == "mapped":
                    os.remove(path)
    return found


def _arm_and_title_text(trial_id, data):
    if trial_id.startswith("NCT"):
        ps = data.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        arms = ps.get("armsInterventionsModule", {})
        out = [ident.get("briefTitle") or "", ident.get("officialTitle") or ""]
        out += [" ".join(str(a.get(k) or "") for k in ("label", "description")) for a in arms.get("armGroups") or []]
        out += [" ".join(str(i.get(k) or "") for k in ("name", "description")) for i in arms.get("interventions") or []]
        return out
    import src.ctis as ctis
    return list(ctis.get_titles(data))


def _conditions(trial_id, data):
    if trial_id.startswith("NCT"):
        return list(data.get("protocolSection", {}).get("conditionsModule", {}).get("conditions") or [])
    import src.ctis as ctis
    return list(ctis.get_conditions(data)) + list(ctis.get_titles(data))


def find_mentions(text, terms, case_sensitive_short=True, gene=None):
    """
    [(start, end, term)] for whole-word mentions of any term in text.

    With `gene`, the terms are names of that gene, and a name glued to a
    protein change counts too ("H3.3K27M", "EGFRvIII"), as in the scan
    (utils/gene_mentions).
    """
    hits = []
    for t in sorted({t for t in terms if t}, key=len, reverse=True):
        flags = 0 if (case_sensitive_short and len(t) <= 4) else re.IGNORECASE
        if gene:
            right = gene_mentions.right_boundary(gene)
            pattern = (_term_pattern(t, right) if flags else
                       r"(?<![A-Za-z0-9])" + re.escape(t) + right)
        else:
            pattern = (_term_pattern(t) if flags else
                       r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])")
        for m in re.finditer(pattern, text, flags):
            if not any(s < m.end() and m.start() < e for s, e, _ in hits):
                hits.append((m.start(), m.end(), t))
    return sorted(hits)


def _snippet(text, start, end, width=110):
    a, b = max(0, start - width), min(len(text), end + width)
    return (("…" if a else "") + html.escape(text[a:start]) + "<mark>" + html.escape(text[start:end])
            + "</mark>" + html.escape(text[end:b]) + ("…" if b < len(text) else "")).replace("\n", " ")


def _one_edit(a, b):
    """True when a and b differ by one substitution or one adjacent swap."""
    if a == b or len(a) != len(b):
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diff) == 1:
        return True
    return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def near_misses(sections, symbol, limit=3):
    """
    Passages with a token one typo away from the symbol ("KTM2A" for KMT2A,
    2023-504694-20-00). Symbols shorter than 4 characters are skipped: one
    edit from a 3-letter symbol is mostly other words.
    """
    if len(symbol) < 4:
        return []
    out = []
    for name, text in sections:
        for m in re.finditer(r"[A-Za-z0-9]+", text):
            if _one_edit(m.group(0).upper(), symbol.upper()):
                out.append((f"{name}, near-miss spelling", _snippet(text, m.start(), m.end())))
                if len(out) >= limit:
                    return out
    return out


def evidence(sections, terms, limit=4, gene=None):
    out = []
    for name, text in sections:
        hits = find_mentions(text, terms, gene=gene)
        if gene:
            # An H3 mutation written without a gene, for the H3 genes it can
            # mean; "H3 K27-altered" and "H3K27me3" are not in it.
            hits = sorted(hits + [(s, e, text[s:e]) for s, e, genes in gene_mentions.histone_variants(text)
                                  if gene in genes and not any(a < e and s < b for a, b, _ in hits)])
        for s, e, _ in hits[:limit]:
            out.append((name, _snippet(text, s, e)))
    return out


# -------------------------------------------------------------------- build

class Reference:
    """Reference data loaded once per run."""

    def __init__(self):
        self.parent, self.level1, self.descendants = get_lineage()
        self.names = set(self.descendants)
        self.aliases = {}
        for alias, name in rv._diagnosis_aliases().items():
            self.aliases.setdefault(name, set()).add(alias)
        self.gene_aliases = _gene_aliases()
        self.synonyms = rv.gene_synonym_mapping()
        self.curated = rv.curated_aliases()
        self.curated_groups = rv.curated_group_aliases()

    def dx_terms(self, name):
        return {name, re.sub(r",\s*NOS$", "", name)} | self.aliases.get(name, set())

    def gene_terms(self, symbol):
        """
        Terms that count as the text naming the gene: the symbol, the curated
        aliases (multi-gene addendum rows included, as in the scan: "H3.3"
        for H3-3A), and any alias the pipeline itself resolves to this symbol.
        """
        curated = set(self.curated.get(symbol, ())) | set(self.curated_groups.get(symbol, ()))
        return {symbol} | curated | {a for a in self.gene_aliases.get(symbol, ()) if rv.canonical_gene(a) == symbol}

    def weak_gene_terms(self, symbol):
        """
        Other NCBI aliases (MLL for KMT2A, N-MYC for MYCN, but also ALL and CML
        for BCR, ROS for ROS1). Shown to the curator, never counted as support.
        """
        return {a for a in self.gene_aliases.get(symbol, ()) if len(a) > 2} - self.gene_terms(symbol)

    def ancestors(self, name):
        out, n = [], self.parent.get(name)
        while n:
            out.append(n)
            n = self.parent.get(n)
        return out


def analyse(trial_id, ref):
    path, layer = _layer_of(trial_id)
    raw = open(path).read()
    ctml = yaml.safe_load(raw)
    inc, exc, record = eligibility_text(trial_id)
    sections = [("inclusion", inc), ("exclusion", exc)]
    title = ctml.get("long_title") or ctml.get("short_title") or ""
    conditions = ((record.get("protocolSection") or {}).get("conditionsModule") or {}).get("conditions") or []
    sections_with_title = sections + [("title", title), ("conditions", "; ".join(conditions))]
    tl_genes = translocations.genes_in(inc + "\n" + exc)
    got = collect(ctml)
    items = []

    # Diagnoses.
    off_list = _as_set(ctml.get("diagnosis_off_list"))
    excluded_flag = _as_set(ctml.get("diagnosis_excluded"))
    only_excluded = set(diagnoses_only_in_exclusions(got["diagnoses"], sections[0][1], sections[1][1],
                                                     [t for _, t in sections_with_title[2:]], ref))
    real = [d for d in dict.fromkeys(got["diagnoses"]) if d not in WILDCARDS]
    if not real and not (set(got["diagnoses"]) & WILDCARDS):
        items.append(Item("no_diagnosis", "(none)", flag="no_diagnosis",
                          evidence=[(n, html.escape(t)) for n, t in sections_with_title[2:] if t]))
    for d in dict.fromkeys(got["diagnoses"]):
        it = Item("diagnosis", d, flag="diagnosis_off_list" if d in off_list else
                  "diagnosis_excluded" if d in excluded_flag else "")
        if d in WILDCARDS:
            it.note = "basket wildcard"
        elif str(d).startswith("!"):
            it.note = "excluded diagnosis (with its subtypes)"
        elif d in only_excluded:
            it.evidence = evidence(sections_with_title[1:2], ref.dx_terms(d), limit=2)
            it.note = "only named in the exclusion criteria: probably an exclusion, not a diagnosis"
        elif d not in ref.names:
            it.note = "NOT an OncoTree name"
        else:
            it.evidence = evidence(sections_with_title, ref.dx_terms(d), limit=2)
            if it.evidence:
                it.note = "named in text"
            else:
                named = next((a for a in ref.ancestors(d)
                              if a not in ref.level1 and evidence(sections_with_title, ref.dx_terms(a), 1)), None)
                it.note = f"parent named in text: {named}" if named else "not named in text"
                if named:
                    it.evidence = evidence(sections_with_title, ref.dx_terms(named), limit=2)
        items.append(it)

    # Genomic criteria.
    for g in got["genomic"]:
        sym = str(g.get("hugo_symbol", ""))
        side = "exclusion" if str(g.get("variant_category", "")).startswith("!") else "inclusion"
        label = f"{sym} {g.get('variant_category', '')}".strip()
        it = Item("gene", label, flag="gene_unsupported" if g.get("gene_unsupported") else "", side=side,
                  evidence=evidence(sections, ref.gene_terms(sym), gene=sym))
        tl = tl_genes.get(sym)
        if tl:
            it.evidence += [("translocation", html.escape(x)) for x in tl]
        if not rv.canonical_gene(sym):
            it.note = "not an accepted gene symbol"
        elif it.evidence and it.flag:
            # The mapper checks each arm's own criteria text, which is not
            # saved in the CTML; the whole trial text names the gene.
            it.note = "only named in the trial text, not in this arm's criteria: check it belongs to this arm"
        elif not it.evidence:
            weak = []
            for name, text in sections:
                for s, e, term in find_mentions(text, ref.weak_gene_terms(sym))[:3]:
                    weak.append((f"{name}, ambiguous alias {html.escape(term)}: check the meaning", _snippet(text, s, e)))
            near = near_misses(sections, sym)
            it.evidence = near + weak
            it.note = ("only a near-miss spelling in text" if near else
                       "only an ambiguous alias in text" if weak else "gene not named in text")
        items.append(it)
        partner_raw = g.get("fusion_partner_unverified")
        if partner_raw:
            official = sorted(ref.synonyms.get(str(partner_raw), []))
            note = f"alias of {', '.join(official)}" if official else "no gene with this symbol or alias"
            if sym in official:
                note += f" - the same gene as {sym}, so the pair is {sym}::{sym}: probably wrong"
            items.append(Item("partner", f"{sym}::{partner_raw}", flag="fusion_partner_unverified", side=side,
                              note=note, evidence=evidence(sections, {str(partner_raw)} | set(official))))
        elif g.get("fusion_partner"):
            items.append(Item("partner", f"{sym}::{g['fusion_partner']}", side=side,
                              evidence=evidence(sections, ref.gene_terms(str(g["fusion_partner"])),
                                                gene=str(g["fusion_partner"]))))
        stated = g.get("protein_change_unverified") or g.get("protein_change_stated") or g.get("protein_change")
        if stated:
            r = protein_change.normalise(sym, str(stated))
            note = f"{r.status}: {r.hgvs or r.detail}"
            if not r.verified:
                # Often the change is right and the gene is wrong: T315I put
                # on BCR instead of ABL1 (2023-508129-28-00).
                others = sorted({str(x.get(k)) for x in got["genomic"] for k in ("hugo_symbol", "fusion_partner")
                                 if x.get(k) and str(x.get(k)) != sym})
                fits = [o for o in others if protein_change.normalise(o, str(stated)).verified]
                if fits:
                    note += f" - but it fits {', '.join(fits)} ({protein_change.normalise(fits[0], str(stated)).hgvs}): " \
                            f"probably put on the wrong gene"
            items.append(Item("protein", f"{sym} {stated}", side=side,
                              flag="protein_change_unverified" if g.get("protein_change_unverified") else "",
                              note=note,
                              evidence=evidence(sections, {str(stated).replace("p.", "")}, limit=3)))

    # Ages.
    lo, hi = registry_ages(record)
    items.append(Item("age", " and ".join(got["ages"]) or "(no age bound)",
                      note=f"registry: min {lo or '-'}, max {hi or '-'}" if record else ""))

    return {"trial_id": trial_id, "layer": layer, "path": path, "title": title, "raw": raw,
            "sections": sections, "conditions": conditions, "items": items,
            "flags": sorted({i.flag for i in items if i.flag}),
            "mentions": [t for i in items if i.kind in ("diagnosis", "gene", "partner") for t in
                         (ref.dx_terms(i.value) if i.kind == "diagnosis" else
                          ref.gene_terms(i.value.split()[0].split("::")[-1]))]}


# -------------------------------------------------------------------- html

CSS = """
body{font:14px/1.45 -apple-system,Helvetica,Arial,sans-serif;margin:24px;max-width:1200px;color:#222}
h1{font-size:19px;margin:0 0 4px} h2{font-size:15px;margin:22px 0 6px;border-bottom:1px solid #ddd}
.flag{background:#fdecea;border-left:4px solid #c0392b;padding:6px 10px;margin:6px 0}
.ok{color:#1e7e34} .warn{color:#b35900} .bad{color:#c0392b;font-weight:600}
table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid #eee;padding:4px 6px;vertical-align:top;text-align:left}
th{background:#f6f6f6} mark{background:#fff2a8} mark.hit{background:#ffd6d6}
.ev{font-size:12.5px;color:#444} .text{white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:10px;font-size:13px}
code{background:#f3f3f3;padding:1px 4px} .muted{color:#888}
"""


def _note_class(note):
    if note.startswith("named") or note.startswith("verified") or note.startswith("alias of") and "wrong" not in note:
        return "ok"
    if note.startswith(("parent", "registry", "only")) or note == "basket wildcard":
        return "warn"
    return "bad" if note else ""


def _highlight(text, terms):
    out, last = [], 0
    for s, e, _ in find_mentions(text, terms):
        out.append(html.escape(text[last:s]) + "<mark>" + html.escape(text[s:e]) + "</mark>")
        last = e
    return "".join(out) + html.escape(text[last:])


def render(a):
    tid = a["trial_id"]
    link = (f"https://clinicaltrials.gov/study/{tid}" if tid.startswith("NCT")
            else f"https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT={tid}")
    h = [f"<!doctype html><meta charset='utf-8'><title>{tid}</title><style>{CSS}</style>",
         f"<p class='muted'><a href='index.html'>&larr; queue</a></p>",
         f"<h1>{tid} <span class='muted'>({a['layer']})</span></h1>",
         f"<div>{html.escape(a['title'])}</div><div class='muted'><a href='{link}'>registry record</a>"
         f" &middot; file: <code>{html.escape(a['path'])}</code></div>"]
    if a["conditions"]:
        h.append(f"<div class='muted'>registry conditions: {html.escape('; '.join(a['conditions']))}</div>")

    h.append("<h2>Flags to resolve</h2>")
    flagged = [i for i in a["items"] if i.flag]
    if not flagged:
        h.append("<p class='ok'>No flags. Check the items below against the text.</p>")
    for i in flagged:
        h.append(f"<div class='flag'><b>{html.escape(i.flag)}</b>: {html.escape(i.value)}"
                 + (f" <span class='{_note_class(i.note)}'>({html.escape(i.note)})</span>" if i.note else "")
                 + f"<div class='ev'>{html.escape(ADVICE.get(i.flag, ''))}</div>"
                 + "".join(f"<div class='ev'>[{n}] {s}</div>" for n, s in i.evidence[:4])
                 + ("" if i.evidence else "<div class='ev bad'>no supporting passage found</div>") + "</div>")

    for kind, heading in (("diagnosis", "Diagnoses"), ("gene", "Genomic criteria"), ("partner", "Fusion partners"),
                          ("protein", "Protein changes"), ("age", "Age")):
        rows = [i for i in a["items"] if i.kind == kind]
        if not rows:
            continue
        h.append(f"<h2>{heading} ({len(rows)})</h2><table><tr><th>item</th><th>side</th><th>check</th><th>evidence</th></tr>")
        for i in rows:
            ev = "".join(f"<div class='ev'>[{n}] {s}</div>" for n, s in i.evidence[:2])
            h.append(f"<tr><td>{'<b>&#9873;</b> ' if i.flag else ''}{html.escape(i.value)}</td>"
                     f"<td>{i.side}</td><td class='{_note_class(i.note)}'>{html.escape(i.note)}</td><td>{ev}</td></tr>")
        h.append("</table>")

    for name, text in a["sections"]:
        h.append(f"<h2>Eligibility: {name}</h2><div class='text'>{_highlight(text, a['mentions']) or '<i>empty</i>'}</div>")
    h.append(f"<h2>To finish</h2><p>Edit <code>{html.escape(a['path'])}</code>, then run "
             f"<code>python -m utils.review_helper accept {tid} --reviewer YOU</code>. "
             f"<code>check {tid}</code> shows what would still be refused.</p>")
    return "\n".join(h)


def render_index(rows, heading):
    h = [f"<!doctype html><meta charset='utf-8'><title>{heading}</title><style>{CSS}</style>",
         f"<h1>{html.escape(heading)}</h1><p class='muted'>generated {datetime.datetime.now():%Y-%m-%d %H:%M}; "
         f"{len(rows)} trials</p><table><tr><th>trial</th><th>flags</th><th>unnamed diagnoses</th><th>title</th></tr>"]
    for a in rows:
        dx = [i for i in a["items"] if i.kind == "diagnosis" and i.note == "not named in text"]
        h.append(f"<tr><td><a href='{a['trial_id']}.html'>{a['trial_id']}</a></td>"
                 f"<td class='bad'>{html.escape(', '.join(a['flags']))}</td><td>{len(dx)}</td>"
                 f"<td>{html.escape(a['title'][:110])}</td></tr>")
    return "\n".join(h + ["</table>"])


def write_sheets(trial_ids, heading, out_dir=SHEET_DIR):
    ref = Reference()
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for tid in trial_ids:
        a = analyse(tid, ref)
        open(os.path.join(out_dir, f"{tid}.html"), "w").write(render(a))
        rows.append(a)
    rows.sort(key=lambda a: (-len(a["flags"]), a["trial_id"]))
    open(os.path.join(out_dir, "index.html"), "w").write(render_index(rows, heading))
    return rows


# ------------------------------------------------------------ accept/check

def problems(ctml, raw):
    """Reasons `accept` refuses this file; empty when it may be accepted."""
    from src.trial_map_manager import TrialMapManager
    out = []
    for k in FLAG_KEYS:
        if re.search(rf"^\s*{k}\s*:", raw, re.M):
            out.append(f"still flagged: {k}")
    import src.match_criteria_mapper as mcm
    for gene in mcm.find_unsatisfiable_genes(ctml.get("treatment_list", ctml)):
        out.append(f"requires and forbids {gene} under one AND: matches nobody")
    if not TrialMapManager._has_diagnosis(ctml):
        out.append("no diagnosis")
    ref_names = set(get_lineage()[2]) | WILDCARDS
    got = collect(ctml)
    for d in got["diagnoses"]:
        # "!Name" excludes that diagnosis and its subtypes (quote it in YAML:
        # a bare leading ! is a YAML tag).
        if str(d).lstrip("!") not in ref_names:
            out.append(f"not an OncoTree name: {d!r}")
    if got["diagnoses"] and all(str(d).startswith("!") for d in got["diagnoses"]):
        out.append("only excluded diagnoses: add the diagnosis the trial enrols")
    for g in got["genomic"]:
        sym = str(g.get("hugo_symbol", ""))
        if not rv.canonical_gene(sym):
            out.append(f"not an accepted gene symbol: {sym!r}")
        if g.get("fusion_partner") and rv.fusion_partner(str(g["fusion_partner"]))[0] != str(g["fusion_partner"]):
            out.append(f"fusion partner not a gene symbol: {g['fusion_partner']!r}")
        if g.get("protein_change"):
            r = protein_change.normalise(sym, str(g["protein_change"]))
            if r.status != protein_change.VERIFIED:
                out.append(f"{sym} {g['protein_change']}: {r.status} ({r.detail})")
    return out


def accept(trial_id, reviewer, note="", replace=False, today=None):
    path, layer = _layer_of(trial_id)
    if layer == "reviewed":
        raise SystemExit(f"{trial_id} is already in {REVIEWED_DIR}")
    if not reviewer.strip():
        raise SystemExit("--reviewer is required")
    raw = open(path).read()
    ctml = yaml.safe_load(raw)
    found = problems(ctml, raw)
    if found:
        raise SystemExit(f"{trial_id} not accepted:\n  - " + "\n  - ".join(found))
    target = os.path.join(REVIEWED_DIR, f"{trial_id}.yaml")
    if os.path.exists(target) and not replace:
        raise SystemExit(f"{target} exists; pass --replace to supersede it (the old copy is kept as .prev)")
    today = today or datetime.date.today().isoformat()
    # Stamp curated_on in place so the curator's formatting survives.
    if re.search(r"^curated_on:.*$", raw, re.M):
        raw = re.sub(r"^curated_on:.*$", f"curated_on: '{today}'", raw, count=1, flags=re.M)
    else:
        raw = f"curated_on: '{today}'\n" + raw
    resolved = _flags_at_entry(trial_id)
    if os.path.exists(target):
        os.replace(target, target + ".prev")
    os.makedirs(REVIEWED_DIR, exist_ok=True)
    with open(target, "w") as fh:
        fh.write(raw)
    if layer == "needs_review":
        os.remove(path)
    new_log = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        if new_log:
            w.writerow(LOG_COLUMNS)
        w.writerow([today, trial_id, reviewer, layer, ",".join(resolved),
                    hashlib.sha256(raw.encode()).hexdigest(), note.replace("\t", " ").replace("\n", " ")])
    return target


def exclude(trial_id, reviewer, reason, today=None):
    """
    Take a trial out of scope: a "skip" row in ref/scope_overrides.tsv, which
    map --all and the index build both honour, and a line in the review log.
    The trial's YAML files are left in place; the index ignores them.
    """
    import utils.oncology_scope as scope
    OVERRIDES = scope.OVERRIDES
    if not reviewer.strip() or not reason.strip():
        raise SystemExit("--reviewer and --reason are required")
    if re.search(r"[\t\n]", reason):
        raise SystemExit("--reason must be one line without tabs")
    current = scope.load_overrides(OVERRIDES).get(trial_id)
    if current and current[0] == "skip":
        raise SystemExit(f"{trial_id} is already excluded: {current[1]}")
    if current:
        raise SystemExit(f"{trial_id} has a 'map' override ({current[1]}); edit {OVERRIDES} by hand")
    layers = [layer for d, layer in ((REVIEW_DIR, "needs_review"), (MAPPED_DIR, "mapped"), (REVIEWED_DIR, "reviewed"))
              if os.path.exists(os.path.join(d, f"{trial_id}.yaml"))]
    today = today or datetime.date.today().isoformat()
    text = open(OVERRIDES).read() if os.path.exists(OVERRIDES) else "trial_id\tdecision\treason\n"
    with open(OVERRIDES, "w") as fh:
        fh.write(text + ("" if text.endswith("\n") else "\n") + f"{trial_id}\tskip\t{reason} ({reviewer}, {today})\n")
    new_log = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        if new_log:
            w.writerow(LOG_COLUMNS)
        w.writerow([today, trial_id, reviewer, ",".join(layers) or "none", "excluded", "", reason])
    return layers


def _flags_at_entry(trial_id):
    """
    The flags the mapper originally set (for the log). The curator's copy has
    them deleted by the time accept runs, so read the mapper's own output:
    the review copy's .prev backup(s), then the mapped copy, then the file
    as it stands. Also the reason for no diagnosis.
    """
    backups = sorted((f for f in os.listdir(REVIEW_DIR) if f.startswith(f"{trial_id}.yaml.prev")),
                     key=lambda f: (len(f), f)) if os.path.isdir(REVIEW_DIR) else []
    for p in ([os.path.join(REVIEW_DIR, backups[0])] if backups else []) + [
            os.path.join(MAPPED_DIR, f"{trial_id}.yaml"), os.path.join(REVIEW_DIR, f"{trial_id}.yaml")]:
        if os.path.exists(p):
            raw = open(p).read()
            return [k for k in FLAG_KEYS if re.search(rf"^\s*{k}\s*:", raw, re.M)]
    return []


# --------------------------------------------------------------------- CLI

def _not_in_index():
    """Trials the index leaves out: out of scope per the report, or a skip override."""
    import utils.oncology_scope as scope
    return set(scope.load_report()) | {t for t, (dec, _) in scope.load_overrides().items() if dec == "skip"}


def _queue_ids():
    """The review queue as the index sees it: no out-of-scope trials, none already reviewed."""
    gone = _not_in_index()
    reviewed = {f[:-5] for f in os.listdir(REVIEWED_DIR)} if os.path.isdir(REVIEWED_DIR) else set()
    return sorted(f[:-5] for f in os.listdir(REVIEW_DIR)
                  if f.endswith(".yaml") and f[:-5] not in gone and f[:-5] not in reviewed)


def audit_sample(n, seed):
    """n random mapped trials that are neither reviewed nor in the queue (roadmap 3.4)."""
    skip = {f[:-5] for d in (REVIEWED_DIR, REVIEW_DIR) if os.path.isdir(d) for f in os.listdir(d)} | _not_in_index()
    pool = sorted(f[:-5] for f in os.listdir(MAPPED_DIR) if f.endswith(".yaml") and f[:-5] not in skip)
    return sorted(random.Random(seed).sample(pool, min(n, len(pool)))), len(pool)


def main(argv=None):
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("queue")
    s = sub.add_parser("sheets"); s.add_argument("trials", nargs="*")
    a = sub.add_parser("audit"); a.add_argument("--n", type=int, default=60); a.add_argument("--seed", type=int, default=20260925)
    c = sub.add_parser("check"); c.add_argument("trial")
    ac = sub.add_parser("accept"); ac.add_argument("trial"); ac.add_argument("--reviewer", required=True)
    ac.add_argument("--note", default=""); ac.add_argument("--replace", action="store_true")
    fx = sub.add_parser("flag-exclusions", help="flag diagnoses named only in exclusion criteria in existing CTML")
    fx.add_argument("--apply", action="store_true", help="write the flag and move mapped trials to review")
    fg = sub.add_parser("flag-unsupported-genes", help="re-run the unsupported-gene check on existing CTML")
    fg.add_argument("--apply", action="store_true", help="write the flag and move mapped trials to review")
    ex = sub.add_parser("exclude"); ex.add_argument("trial"); ex.add_argument("--reviewer", required=True)
    ex.add_argument("--reason", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "queue":
        ref = Reference()
        for tid in _queue_ids():
            an = analyse(tid, ref)
            print(f"{tid}\t{','.join(an['flags'])}\t{an['title'][:80]}")
    elif args.cmd == "sheets":
        rows = write_sheets(args.trials or _queue_ids(), "Review queue" if not args.trials else "Selected trials")
        print(f"{len(rows)} sheets in {SHEET_DIR}/ - open {SHEET_DIR}/index.html")
    elif args.cmd == "audit":
        ids, pool = audit_sample(args.n, args.seed)
        out = f"ctml/audit_{datetime.date.today():%Y-%m-%d}.tsv"
        with open(out, "w", newline="") as fh:
            w = csv.writer(fh, delimiter="\t", lineterminator="\n")
            w.writerow(["trial_id", "verdict", "error_type", "note"])
            for t in ids:
                w.writerow([t, "", "", ""])
        write_sheets(ids, f"Audit sample: {len(ids)} of {pool} mapped trials (seed {args.seed})",
                     out_dir=os.path.join(SHEET_DIR, "audit"))
        print(f"{len(ids)} of {pool} mapped trials -> {out}; sheets in {SHEET_DIR}/audit/index.html")
    elif args.cmd == "check":
        path, layer = _layer_of(args.trial)
        raw = open(path).read()
        found = problems(yaml.safe_load(raw), raw)
        print(f"{args.trial} ({layer}): " + ("ready to accept" if not found else "\n  - " + "\n  - ".join(found)))
    elif args.cmd == "accept":
        print(f"accepted -> {accept(args.trial, args.reviewer, args.note, args.replace)}; logged in {LOG_FILE}")
    elif args.cmd == "flag-exclusions":
        found = flag_exclusions(apply=args.apply)
        for t, layer, hit in found:
            print(f"{t}\t{layer}\t{'; '.join(hit)}")
        moved = sum(1 for _, layer, _ in found if layer == "mapped")
        print(f"{len(found)} trials ({moved} mapped)" + (" flagged; mapped ones moved to the review queue"
              if args.apply else " would be flagged; run with --apply to write"))
    elif args.cmd == "flag-unsupported-genes":
        found = flag_unsupported_genes(apply=args.apply)
        for t, layer, genes, action in found:
            print(f"{t}\t{layer}\t{action}\t{'; '.join(genes)}")
        moved = sum(1 for _, layer, _, a in found if a == "moved to review")
        print(f"{len(found)} trials ({moved} mapped would move to review)" if not args.apply
              else f"{len(found)} trials flagged; {moved} mapped ones moved to the review queue")
    elif args.cmd == "exclude":
        layers = exclude(args.trial, args.reviewer, args.reason)
        print(f"{args.trial} excluded (ref/scope_overrides.tsv; logged in {LOG_FILE}); "
              f"its copies in {', '.join(layers) or 'no layer'} are left in place and dropped at the next index build")


if __name__ == "__main__":
    main()
