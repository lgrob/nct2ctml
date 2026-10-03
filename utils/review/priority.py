"""
The order a curator should work the review queue in, with the reasons.

A queued trial is not published: until a curator resolves it, no patient can
be matched to it. So the queue is ordered by how much a resolved trial would
matter at Kispi, from what is known offline:

- open to recruitment (cache/nct/trial_status.csv, cache/ctis/ctis_status.csv);
- a Kispi trial (ref/local_trial_info.csv, empty until filled in);
- admits children (no lower age bound, or one under 18), and built for them
  (an upper bound of 30 or below);
- a paediatric diagnosis (the leukaemias, CNS tumours, neuroblastoma, the
  paediatric sarcomas and renal, liver, eye and germ-cell tumours, the
  lymphomas of childhood, or a basket);
- a flag that is usually a one-line fix (an age conflict, a contradiction, an
  arm narrower than its step), so the trial comes back quickly.

The score is a plain sum, and every point is listed, so the order can be
argued with. Not known offline, so not used: Swiss sites (the ClinicalTrials.gov
pull keeps no locations, CTIS has none) and the patient cohort.
"""

import csv
import os
import re
from functools import lru_cache

import src.text_rules as text_rules

PAEDIATRIC_ROOTS = (
    "B-Lymphoblastic Leukemia/Lymphoma",
    "T-Lymphoblastic Leukemia/Lymphoma",
    "Acute Myeloid Leukemia",
    "Acute Leukemias of Ambiguous Lineage",
    "Juvenile Myelomonocytic Leukemia",
    "Myelodysplastic Syndromes",
    "Neuroblastoma",
    "Ganglioneuroblastoma",
    "Wilms' Tumor",
    "Rhabdomyosarcoma",
    "Ewing Sarcoma",
    "Ewing Sarcoma of Soft Tissue",
    "Osteosarcoma",
    "Retinoblastoma",
    "Hepatoblastoma",
    "Ovarian Germ Cell Tumor",
    "Non-Seminomatous Germ Cell Tumor",
    "Extra Gonadal Germ Cell Tumor",
    "Germ Cell Tumor, Brain",
    "Hodgkin Lymphoma",
    "Burkitt Lymphoma",
    "Anaplastic Large-Cell Lymphoma ALK Positive",
    "Diffuse Large B-Cell Lymphoma, NOS",
    "Primary Mediastinal (Thymic) Large B-Cell Lymphoma",
    "Synovial Sarcoma",
    "Desmoplastic Small-Round-Cell Tumor",
    "Malignant Rhabdoid Tumor of the Liver",
    "Rhabdoid Cancer",
    "Langerhans Cell Histiocytosis",
)
# Flags whose fix is usually one line once the curator has read the text.
QUICK_FLAGS = frozenset(
    {
        "age_registry_conflict",
        "age_units_implausible",
        "genomic_contradiction",
        "gene_status_contradiction",
        "arm_narrower_than_step",
        "diagnosis_excluded",
    }
)


@lru_cache(maxsize=1)
def _status():
    status = {}
    for path, key in (
        ("cache/nct/trial_status.csv", "nct_id"),
        ("cache/ctis/ctis_status.csv", "ct_number"),
    ):
        if os.path.exists(path):
            for row in csv.DictReader(open(path)):
                status[row.get(key, "")] = (row.get("status") or "").strip().lower()
    return status


@lru_cache(maxsize=1)
def _kispi_trials():
    path = "ref/local_trial_info.csv"
    if not os.path.exists(path):
        return frozenset()
    return frozenset(
        r.get("nct_id", "").strip() for r in csv.DictReader(open(path)) if r.get("nct_id")
    )


@lru_cache(maxsize=1)
def _paediatric_codes():
    from utils.build_trial_index import diagnosis_population

    ref = text_rules._shared_reference()
    return frozenset(diagnosis_population([r for r in PAEDIATRIC_ROOTS if r in ref.names]))


def _lower_age(ctml):
    lows = []
    for a in text_rules.collect(ctml)["ages"]:
        m = re.match(r"^\s*>=?\s*(\d+(?:\.\d+)?)", str(a))
        if m:
            lows.append(float(m.group(1)))
    return max(lows) if lows else None


def _upper_age(ctml):
    highs = []
    for a in text_rules.collect(ctml)["ages"]:
        m = re.match(r"^\s*<=?\s*(\d+(?:\.\d+)?)", str(a))
        if m:
            highs.append(float(m.group(1)))
    return min(highs) if highs else None


def score(trial_id: str, ctml: dict | None, flags=()) -> tuple[int, list[str]]:
    """(score, reasons) for one queued trial; higher is more urgent."""
    from utils.build_trial_index import diagnosis_population

    points, reasons = 0, []
    status = _status().get(trial_id, "")
    if status == "open":
        points += 3
        reasons.append("+3 open")
    elif status:
        points -= 5
        reasons.append(f"-5 {status}")
    if trial_id in _kispi_trials():
        points += 5
        reasons.append("+5 Kispi trial")
    if isinstance(ctml, dict):
        low = _lower_age(ctml)
        if low is None or low < 18:
            points += 3
            reasons.append("+3 admits children" if low is not None else "+3 no lower age bound")
        else:
            points -= 3
            reasons.append(f"-3 adults only (>= {low:g})")
        # Most open trials admit 12-year-olds; one capped at young adulthood
        # was built for children.
        high = _upper_age(ctml)
        if high is not None and high <= 31:
            points += 2
            reasons.append(f"+2 built for children/young adults (< {high:g})")
        dx = [d for d in text_rules.collect(ctml)["diagnoses"] if not d.startswith("!")]
        if not dx:
            reasons.append("no diagnosis yet")
        elif set(dx) & {"_SOLID_", "_LIQUID_"} or diagnosis_population(dx) & _paediatric_codes():
            points += 2
            reasons.append("+2 paediatric diagnosis")
    if QUICK_FLAGS & set(flags):
        points += 1
        reasons.append("+1 usually a quick fix")
    return points, reasons
