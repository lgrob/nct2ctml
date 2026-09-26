"""
Which cached trials are oncology trials, decided before any model is called.

ClinicalTrials.gov's `query.cond` is a search, not a field filter, so a trial
whose exclusion criteria say "no history of cancer" is pulled: warts,
myasthenia gravis, PCOS, antiviral T cells after transplant. CTIS pulls by
age group and so brings in sickle cell disease, SMA and haemophilia. Mapping
them costs model time and produces trials with no diagnosis, which then sit
in the review queue.

A trial is in scope when any of these holds:

- one of its conditions resolves to an Oncotree term, or the conditions
  describe a basket (the pipeline's own rules, so scope and mapping agree);
- its conditions, keywords, brief or official title contain an oncology
  stem or abbreviation from the vocabulary below.

The official title is included because conditions alone miss trials that
describe the procedure rather than the disease: NCT05088226's only condition
is "Peripheral Blood Stem Cell Transplantation", and its official title
names B-cell acute lymphoblastic leukaemia.

This is a skip at *map* time, never a drop at pull time. Every trial is still
pulled and cached. Skipped trials are listed with the reason in
`ctml/out-of-scope.tsv` (`python -m utils.oncology_scope` rewrites it), and a
curator can force either decision per trial in `ref/scope_overrides.tsv`. A trial that is never pulled
is a trial nobody can notice is missing; a skipped one is on a list.

Policy recorded 2026-09-23, from reading all 84 trials this skips across both
registries: supportive care (antiviral T cells, GvHD), cancer predisposition
syndromes without a tumour criterion (tuberous sclerosis, Peutz-Jeghers),
vascular anomalies (infantile haemangioma, lymphatic and arteriovenous
malformations), AL amyloidosis, CAR-T long-term follow-up and drug rollover
studies are out of scope. None of them enrols a patient on a tumour diagnosis
or variant. Override in the file if that changes.
"""
import csv
import os
import re

import config

# Stems, matched case-insensitively anywhere in the text. A stem that is
# missing here is a false skip; the four found so far (germinoma, NSCLC,
# kaposiform hemangioendothelioma, insulinoma) were each a missing stem.
_STEMS = (
    "cancer", "tumor", "tumour", "neoplas", "carcino", "sarcom", "lymphom",
    "leukemi", "leukaemi", "blastom", "gliom", "glioblast", "melanom", "myelom",
    "germinom", "seminom", "teratom", "astrocytom", "ependymom", "medulloblast",
    "neuroblast", "nephroblast", "wilms", "retinoblast", "hepatoblast", "rhabdo",
    "ewing", "malignan", "metasta", "oncolog", "myelodysplas", "histiocyt",
    "mesotheliom", "craniopharyngiom", "meningiom", "schwannom", "neurofibrom",
    "pheochromocytom", "paragangliom", "chordom", "myeloprolif", "mastocytos",
    "hemangioendotheliom", "haemangioendotheliom", "langerhans", "hodgkin",
    "waldenstr", "macroglobulin", "plasmacyt", "chemotherap", "radiotherap",
    "insulinom",
)
# Abbreviations, matched case-sensitively as whole words: "ALL" is acute
# lymphoblastic leukaemia, "all" is not.
_ABBREVIATIONS = (
    "NSCLC", "SCLC", "AML", "ALL", "CML", "CLL", "MDS", "JMML", "HCC", "RCC",
    "DIPG", "DMG", "HGG", "LGG", "GBM", "NHL", "HL", "LCH", "MPNST", "ATRT",
)
_STEM_RX = re.compile("|".join(_STEMS), re.I)

# Studies that enrol only patients from an earlier study - long-term
# follow-up after cell or gene therapy, drug rollover, continued access. The
# policy above puts them out of scope (no new patient can enter them), but
# they name cancers, so the vocabulary let 18 through in the first full run
# (reported by the user on 2023-507041-28-00, a Kite follow-up study whose
# only condition is "Solid and Hematological Malignancies"). Matched in the
# titles and keywords only: inclusion criteria say "prior to any study
# procedure" far too often to be used.
_FOLLOW_ON_RX = re.compile(
    r"long[\s-]*term[\s-]+follow[\s-]*up|\bLTFU\b|roll[\s-]*over|continued\s+(?:access|treatment)"
    r"|extension\s+study|continuation\s+study", re.I)

# Phrases that contain a stem but name no tumour. Masked before the
# vocabulary is matched, so they cannot put a trial in scope; the rest of
# the text still can. Each was a trial wrongly in scope in the first full
# run (2026-09-25), found by listing every trial whose conditions hold no
# oncology term:
# - an antigen: anti-Leucine-rich Glioma-Inactivated 1 (LGI1) encephalitis,
#   2023-504226-18-00;
# - a cytokine: tumor necrosis factor inhibitors in juvenile idiopathic
#   arthritis, 2023-510118-21-00 and 2024-513017-12-00;
# - an institution: "Memorial Sloan Kettering Cancer Center" in the keywords of
#   sickle cell and aplastic anaemia trials, NCT05736419 and NCT06430788;
# - a malformation: "myelom" (myeloma) inside "myelomeningocele", spina
#   bifida, NCT05491525.
_NOT_A_TUMOUR = re.compile(
    r"glioma[\s-]+inactivated"
    r"|tumou?r[\s-]+necrosis[\s-]+factor"
    r"|cancer\s+(?:center|centre|institute|research|society|hospital)"
    r"|myelomeningocele"
    # - safety monitoring after gene therapy: "Risk of Malignancy Due to
    #   Insertional Oncogenesis" in metachromatic leukodystrophy,
    #   2025-522275-28-00 (reported by the user, 2026-09-26).
    r"|risk\s+of\s+(?:secondary\s+)?malignanc\w*|insertional\s+oncogenesis",
    re.I)
_ABBR_RX = re.compile(r"\b(?:" + "|".join(_ABBREVIATIONS) + r")\b")

OVERRIDES = getattr(config, "SCOPE_OVERRIDES_FILE_PATH", "ref/scope_overrides.tsv")
REPORT = getattr(config, "SCOPE_REPORT_FILE_PATH", "ctml/out-of-scope.tsv")


def matched_terms(texts):
    """The vocabulary terms found in `texts`, in order of first appearance."""
    text = _NOT_A_TUMOUR.sub(" ", " | ".join(t for t in texts if t))
    found = [m.group(0) for m in _STEM_RX.finditer(text)]
    found += [m.group(0) for m in _ABBR_RX.finditer(text)]
    return list(dict.fromkeys(found))


def load_report(path=None):
    """trial_id -> reason from the out-of-scope report. Missing file means none."""
    path = path or REPORT
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as handle:
        return {row["trial_id"]: row.get("reason", "") for row in csv.DictReader(handle, delimiter="\t")}


def load_overrides(path=OVERRIDES):
    """trial_id -> ("map" | "skip", reason). Missing file means no overrides."""
    if not os.path.exists(path):
        return {}
    overrides = {}
    with open(path, newline="") as handle:
        for row in csv.DictReader((l for l in handle if not l.startswith("#")), delimiter="\t"):
            decision = (row.get("decision") or "").strip().lower()
            if decision not in ("map", "skip"):
                raise ValueError(f"{path}: decision for {row.get('trial_id')!r} must be map or skip")
            overrides[row["trial_id"].strip()] = (decision, (row.get("reason") or "").strip())
    return overrides


def _nct_texts(trial_data):
    ps = trial_data.get("protocolSection", {})
    cm, im = ps.get("conditionsModule", {}), ps.get("identificationModule", {})
    return (cm.get("conditions") or []), (cm.get("keywords") or []) + [
        im.get("briefTitle") or "", im.get("officialTitle") or ""]


def _ctis_texts(trial_data):
    import src.ctis as ctis
    return ctis.get_conditions(trial_data), list(ctis.get_titles(trial_data))


def assess(trial_id, trial_data, registry, overrides=None):
    """
    (in_scope, reason) for one cached trial record.

    `registry` is "nct" or "ctis". The reason names what decided it: the
    Oncotree terms or vocabulary matched, an override, or that nothing did.
    """
    overrides = load_overrides() if overrides is None else overrides
    if trial_id in overrides:
        decision, why = overrides[trial_id]
        return decision == "map", f"override: {why}"

    conditions, other = (_nct_texts if registry == "nct" else _ctis_texts)(trial_data)

    import utils.reference_validation as rv
    import src.clinical_trials_gov as ctg
    follow_on = _FOLLOW_ON_RX.search(" | ".join(t for t in other if t))
    if follow_on:
        return False, f"follow-on study ('{follow_on.group(0)}'): enrols only patients from an earlier study"

    oncotree = rv.diagnoses_from_conditions(conditions, trial_id)
    if oncotree:
        return True, f"conditions name {sorted(oncotree)[:3]}"
    if ctg.basket_wildcards(conditions, trial_id):
        return True, "conditions describe a basket"
    terms = matched_terms(list(conditions) + list(other))
    if terms:
        return True, f"mentions {terms[:3]}"
    return False, f"no oncology term in conditions, keywords or titles: {list(conditions)[:3]}"


def write_report(rows, path=REPORT, registry=None):
    """
    Write the skipped trials as a sorted TSV: trial_id, registry, reason.

    With `registry`, only that registry's rows are replaced, so mapping NCT
    and then CTIS leaves both lists in the report.
    """
    rows = list(rows)
    if registry and os.path.exists(path):
        with open(path, newline="") as handle:
            kept = [tuple(r) for r in list(csv.reader(handle, delimiter="\t"))[1:]
                    if len(r) == 3 and r[1] != registry]
        rows += kept
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["trial_id", "registry", "reason"])
        for row in sorted(rows):
            writer.writerow(row)


def main():
    """Assess every cached trial and write the out-of-scope report."""
    import argparse
    import glob
    import json
    parser = argparse.ArgumentParser(description="List cached trials the map step will skip.")
    parser.add_argument("--nct", default="cache/nct")
    parser.add_argument("--ctis", default="cache/ctis")
    parser.add_argument("--out", default=REPORT)
    args = parser.parse_args()
    overrides = load_overrides()
    skipped, total = [], 0
    for registry, folder, pattern in (("nct", args.nct, "NCT*.json"), ("ctis", args.ctis, "*.json")):
        for path in sorted(glob.glob(os.path.join(folder, pattern))):
            trial_id = os.path.basename(path)[:-5]
            try:
                with open(path) as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            total += 1
            in_scope, reason = assess(trial_id, data, registry, overrides)
            if not in_scope:
                skipped.append((trial_id, registry, reason))
    write_report(skipped, args.out)
    print(f"{len(skipped)} of {total} cached trials out of scope; listed in {args.out}")


if __name__ == "__main__":
    main()
