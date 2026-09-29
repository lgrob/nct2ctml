"""
The evidence behind each flag: a trial's own text (eligibility criteria as
the mapper split them, arms, titles, conditions) and the passages in it that
mention each diagnosis, gene or protein change. analyse() turns one trial
into the list of items a review sheet shows.
"""

import html
import json
import os
import re

import yaml

import src.text_rules as text_rules
import utils.gene_mentions as gene_mentions
import utils.protein_change as protein_change
import utils.reference_validation as rv
import utils.review.common as common
import utils.translocations as translocations


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


def _arm_and_title_text(trial_id, data):
    if trial_id.startswith("NCT"):
        ps = data.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        arms = ps.get("armsInterventionsModule", {})
        out = [ident.get("briefTitle") or "", ident.get("officialTitle") or ""]
        out += [
            " ".join(str(a.get(k) or "") for k in ("label", "description"))
            for a in arms.get("armGroups") or []
        ]
        out += [
            " ".join(str(i.get(k) or "") for k in ("name", "description"))
            for i in arms.get("interventions") or []
        ]
        return out
    import src.ctis as ctis

    return list(ctis.get_titles(data))


def _conditions(trial_id, data):
    if trial_id.startswith("NCT"):
        return list(
            data.get("protocolSection", {}).get("conditionsModule", {}).get("conditions") or []
        )
    import src.ctis as ctis

    return list(ctis.get_conditions(data)) + list(ctis.get_titles(data))


def _snippet(text, start, end, width=110):
    a, b = max(0, start - width), min(len(text), end + width)
    return (
        ("…" if a else "")
        + html.escape(text[a:start])
        + "<mark>"
        + html.escape(text[start:end])
        + "</mark>"
        + html.escape(text[end:b])
        + ("…" if b < len(text) else "")
    ).replace("\n", " ")


def _one_edit(a, b):
    """True when a and b differ by one substitution or one adjacent swap."""
    if a == b or len(a) != len(b):
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diff) == 1:
        return True
    return (
        len(diff) == 2
        and diff[1] == diff[0] + 1
        and a[diff[0]] == b[diff[1]]
        and a[diff[1]] == b[diff[0]]
    )


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
        hits = text_rules.find_mentions(text, terms, gene=gene)
        if gene:
            # An H3 mutation written without a gene, for the H3 genes it can
            # mean; "H3 K27-altered" and "H3K27me3" are not in it.
            hits = sorted(
                hits
                + [
                    (s, e, text[s:e])
                    for s, e, genes in gene_mentions.histone_variants(text)
                    if gene in genes and not any(a < e and s < b for a, b, _ in hits)
                ]
            )
        for s, e, _ in hits[:limit]:
            out.append((name, _snippet(text, s, e)))
    return out


def _no_diagnosis_items(got, sections_with_title):
    real = [d for d in dict.fromkeys(got["diagnoses"]) if d not in common.WILDCARDS]
    if real or set(got["diagnoses"]) & common.WILDCARDS:
        return []
    return [
        common.Item(
            "no_diagnosis",
            "(none)",
            flag="no_diagnosis",
            evidence=[(n, html.escape(t)) for n, t in sections_with_title[2:] if t],
        )
    ]


def _kept_out_gene_items(ctml, sections_with_title, ref):
    """Genes kept out of the tree by the roles prompt (information only)."""
    items = []
    for entry in common._as_list(ctml.get("gene_role_dropped")):
        gname = str(entry).split(" (")[0]
        items.append(
            common.Item(
                "gene",
                f"{entry} (kept out of the match tree)",
                evidence=evidence(sections_with_title, ref.gene_terms(gname), limit=2),
                note="information: not required of every patient per the model; published as genes_not_required",
            )
        )
    return items


def _remap_drop_items(ctml, sections_with_title, ref):
    """
    A re-map dropped these; shown with the text that names them, so the
    curator can add back the ones the trial enrols.
    """
    return [
        common.Item(
            "diagnosis",
            f"{d} (dropped by the re-map)",
            flag="remap_dropped_diagnoses",
            evidence=evidence(sections_with_title, ref.dx_terms(d), limit=2),
            note="was in the previous version (.yaml.prev); not named in the exclusion criteria",
        )
        for d in common._as_list(ctml.get("remap_dropped_diagnoses"))
    ]


def _diagnosis_item(d, off_list, excluded_flag, only_excluded, sections_with_title, ref):
    it = common.Item(
        "diagnosis",
        d,
        flag="diagnosis_off_list"
        if d in off_list
        else "diagnosis_excluded"
        if d in excluded_flag
        else "",
    )
    if d in common.WILDCARDS:
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
            named = next(
                (
                    a
                    for a in ref.ancestors(d)
                    if a not in ref.level1 and evidence(sections_with_title, ref.dx_terms(a), 1)
                ),
                None,
            )
            it.note = f"parent named in text: {named}" if named else "not named in text"
            if named:
                it.evidence = evidence(sections_with_title, ref.dx_terms(named), limit=2)
    return it


def _diagnosis_items(ctml, got, sections, sections_with_title, ref):
    off_list = common._as_set(ctml.get("diagnosis_off_list"))
    excluded_flag = common._as_set(ctml.get("diagnosis_excluded"))
    only_excluded = set(
        text_rules.diagnoses_only_in_exclusions(
            got["diagnoses"],
            sections[0][1],
            sections[1][1],
            [t for _, t in sections_with_title[2:]],
            ref,
        )
    )
    return [
        _diagnosis_item(d, off_list, excluded_flag, only_excluded, sections_with_title, ref)
        for d in dict.fromkeys(got["diagnoses"])
    ]


def _gene_status_items(ctml, inc, ref):
    """Genes required although the text says absent / irrelevant."""
    if not ctml.get("gene_status_contradiction"):
        return []
    live = text_rules.gene_status_contradictions(ctml, inc, ref)
    return [
        common.Item(
            "gene",
            f"{gname} (required, but the text says absent or irrelevant)",
            flag="gene_status_contradiction",
            evidence=[("inclusion", html.escape(live[gname]))] if gname in live else [],
            note="the tree requires an alteration here; the text does not",
        )
        for gname in common._as_list(ctml.get("gene_status_contradiction"))
    ]


def _gene_item(g, sym, side, sections, tl_genes, ref):
    label = f"{sym} {g.get('variant_category', '')}".strip()
    it = common.Item(
        "gene",
        label,
        flag="gene_unsupported" if g.get("gene_unsupported") else "",
        side=side,
        evidence=evidence(sections, ref.gene_terms(sym), gene=sym),
    )
    tl = tl_genes.get(sym)
    if tl:
        it.evidence += [("translocation", html.escape(x)) for x in tl]
    if not rv.canonical_gene(sym):
        it.note = "not an accepted gene symbol"
    elif it.evidence and it.flag:
        # The mapper checks each arm's own criteria text, which is not
        # saved in the CTML; the whole trial text names the gene.
        it.note = (
            "only named in the trial text, not in this arm's criteria: check it belongs to this arm"
        )
    elif not it.evidence:
        weak = []
        for name, text in sections:
            for s, e, term in text_rules.find_mentions(text, ref.weak_gene_terms(sym))[:3]:
                weak.append(
                    (
                        f"{name}, ambiguous alias {html.escape(term)}: check the meaning",
                        _snippet(text, s, e),
                    )
                )
        near = near_misses(sections, sym)
        it.evidence = near + weak
        it.note = (
            "only a near-miss spelling in text"
            if near
            else "only an ambiguous alias in text"
            if weak
            else "gene not named in text"
        )
    return it


def _partner_items(g, sym, side, sections, ref):
    partner_raw = g.get("fusion_partner_unverified")
    if partner_raw:
        official = sorted(ref.synonyms.get(str(partner_raw), []))
        note = (
            f"alias of {', '.join(official)}" if official else "no gene with this symbol or alias"
        )
        if sym in official:
            note += f" - the same gene as {sym}, so the pair is {sym}::{sym}: probably wrong"
        return [
            common.Item(
                "partner",
                f"{sym}::{partner_raw}",
                flag="fusion_partner_unverified",
                side=side,
                note=note,
                evidence=evidence(sections, {str(partner_raw)} | set(official)),
            )
        ]
    if g.get("fusion_partner"):
        return [
            common.Item(
                "partner",
                f"{sym}::{g['fusion_partner']}",
                side=side,
                evidence=evidence(
                    sections,
                    ref.gene_terms(str(g["fusion_partner"])),
                    gene=str(g["fusion_partner"]),
                ),
            )
        ]
    return []


def _protein_items(g, sym, side, got, sections):
    stated = (
        g.get("protein_change_unverified")
        or g.get("protein_change_stated")
        or g.get("protein_change")
    )
    if not stated:
        return []
    r = protein_change.normalise(sym, str(stated))
    note = f"{r.status}: {r.hgvs or r.detail}"
    if not r.verified:
        # Often the change is right and the gene is wrong: T315I put
        # on BCR instead of ABL1 (2023-508129-28-00).
        others = sorted(
            {
                str(x.get(k))
                for x in got["genomic"]
                for k in ("hugo_symbol", "fusion_partner")
                if x.get(k) and str(x.get(k)) != sym
            }
        )
        fits = [o for o in others if protein_change.normalise(o, str(stated)).verified]
        if fits:
            note += (
                f" - but it fits {', '.join(fits)} ({protein_change.normalise(fits[0], str(stated)).hgvs}): "
                f"probably put on the wrong gene"
            )
    return [
        common.Item(
            "protein",
            f"{sym} {stated}",
            side=side,
            flag="protein_change_unverified" if g.get("protein_change_unverified") else "",
            note=note,
            evidence=evidence(sections, {str(stated).replace("p.", "")}, limit=3),
        )
    ]


def _genomic_items(got, sections, tl_genes, ref):
    """Per genomic criterion: the gene, then its fusion partner, then its protein change."""
    items = []
    for g in got["genomic"]:
        sym = str(g.get("hugo_symbol", ""))
        side = "exclusion" if str(g.get("variant_category", "")).startswith("!") else "inclusion"
        items.append(_gene_item(g, sym, side, sections, tl_genes, ref))
        items += _partner_items(g, sym, side, sections, ref)
        items += _protein_items(g, sym, side, got, sections)
    return items


def _age_item(got, record):
    lo, hi = registry_ages(record)
    return common.Item(
        "age",
        " and ".join(got["ages"]) or "(no age bound)",
        note=f"registry: min {lo or '-'}, max {hi or '-'}" if record else "",
    )


def _mentions(items, ref):
    return [
        t
        for i in items
        if i.kind in ("diagnosis", "gene", "partner")
        for t in (
            ref.dx_terms(i.value)
            if i.kind == "diagnosis"
            else ref.gene_terms(i.value.split()[0].split("::")[-1])
        )
    ]


def analyse(trial_id, ref):
    """
    Everything a review sheet shows for one trial, as items in a fixed order:
    no diagnosis, genes kept out of the tree, diagnoses a re-map dropped, each
    diagnosis, gene-status contradictions, each genomic criterion (gene,
    partner, protein change), and the age.
    """
    path, layer = common._layer_of(trial_id)
    raw = open(path).read()
    ctml = yaml.safe_load(raw)
    inc, exc, record = eligibility_text(trial_id)
    sections = [("inclusion", inc), ("exclusion", exc)]
    title = ctml.get("long_title") or ctml.get("short_title") or ""
    conditions = ((record.get("protocolSection") or {}).get("conditionsModule") or {}).get(
        "conditions"
    ) or []
    sections_with_title = sections + [("title", title), ("conditions", "; ".join(conditions))]
    tl_genes = translocations.genes_in(inc + "\n" + exc)
    got = text_rules.collect(ctml)
    items = (
        _no_diagnosis_items(got, sections_with_title)
        + _kept_out_gene_items(ctml, sections_with_title, ref)
        + _remap_drop_items(ctml, sections_with_title, ref)
        + _diagnosis_items(ctml, got, sections, sections_with_title, ref)
        + _gene_status_items(ctml, inc, ref)
        + _genomic_items(got, sections, tl_genes, ref)
        + [_age_item(got, record)]
    )
    return {
        "trial_id": trial_id,
        "layer": layer,
        "path": path,
        "title": title,
        "raw": raw,
        "sections": sections,
        "conditions": conditions,
        "items": items,
        "flags": sorted({i.flag for i in items if i.flag}),
        "mentions": _mentions(items, ref),
    }
