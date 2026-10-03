"""
Curator confirmation of an audit's verdicts: turn AI-read error rates into
curator-confirmed ones.

The third audit (doc/runs/2026-10-03-3.4-audit-3.md) was read by Claude: six
readers and a second Claude reader. Its rates (50% of published trials with
an error, 23% losing patients) rest on no human judgement. Here a curator
reads the same trials and records a verdict, and the rates are re-estimated
from the curator's verdicts.

- What is shown: the trial as it was audited, read from the release the
  audit sampled (releases/<tag>.tar.gz, inputs/cache/ctml), beside the
  registry text. Later rebuilds have changed many trials since.
- Blind by default: the curator records a verdict before the AI verdict is
  shown, so it cannot anchor them. Revealing it first is allowed and is
  recorded (saw_ai = yes).
- The sample: every AI error and borderline verdict, and a seeded random 20
  of the trials the AI judged correct. The estimates weight each stratum back
  to the 150 audited trials (stratified estimate, 95% CI).
- Stored in ctml/<audit>_confirmations.tsv, one line per decision; the last
  line for a trial counts.

Nothing here edits a trial. It records what the curator thinks of a verdict.
"""

import csv
import datetime
import math
import os
import random
import tarfile
from functools import lru_cache

import yaml

AUDIT_TSV = "ctml/audit_2026-10-03.tsv"
RELEASE = "index-2026.10.03"
CONFIRM_TSV = "ctml/audit_2026-10-03_confirmations.tsv"
CORRECT_SAMPLE = 20
SEED = 20261007
COLUMNS = [
    "date",
    "trial_id",
    "reviewer",
    "verdict",
    "effect",
    "saw_ai",
    "ai_verdict",
    "ai_effect",
    "comment",
]
VERDICTS = ("correct", "error", "borderline")
EFFECTS = ("loses", "over-match", "both")


@lru_cache(maxsize=1)
def audit_rows() -> dict[str, dict]:
    return {r["trial_id"]: r for r in csv.DictReader(open(AUDIT_TSV), delimiter="\t")}


def stratum(row) -> str:
    return row["verdict"]  # correct | error | borderline


@lru_cache(maxsize=1)
def sample() -> list[str]:
    """Every AI error and borderline verdict, and a seeded sample of the correct ones."""
    rows = audit_rows()
    flagged = sorted(t for t, r in rows.items() if r["verdict"] != "correct")
    correct = sorted(t for t, r in rows.items() if r["verdict"] == "correct")
    picked = sorted(random.Random(SEED).sample(correct, min(CORRECT_SAMPLE, len(correct))))
    return flagged + picked


@lru_cache(maxsize=1)
def _archive():
    path = f"releases/{RELEASE}.tar.gz"
    if not os.path.exists(path):
        raise SystemExit(
            f"{path} is missing: the audit was read against that release. Download it from the "
            f"GitHub release {RELEASE} into releases/."
        )
    return tarfile.open(path)


def basis_ctml(trial_id: str) -> dict:
    """The trial as it was audited."""
    member = _archive().extractfile(f"{RELEASE}/inputs/cache/ctml/{trial_id}.yaml")
    doc = yaml.safe_load(member.read())
    doc.pop("_provenance", None)
    return doc


def criteria_lines(ctml: dict) -> list[str]:
    """The match tree as indented lines a curator can read at a glance."""
    out = []

    def show(node, depth):
        pad = "  " * depth
        if isinstance(node, list):
            for x in node:
                show(x, depth)
        elif isinstance(node, dict):
            for k, v in node.items():
                if k in ("and", "or"):
                    out.append(f"{pad}{k.upper()}:")
                    show(v, depth + 1)
                elif k == "clinical":
                    out.append(pad + "  ".join(f"{a}: {b}" for a, b in v.items()))
                elif k == "genomic":
                    out.append(pad + "gene " + "  ".join(f"{a}: {b}" for a, b in v.items()))

    for step in (ctml.get("treatment_list") or {}).get("step", []) or []:
        out.append("STEP (every patient):")
        show(step.get("match"), 1)
        for arm in step.get("arm", []) or []:
            if arm.get("match"):
                out.append(f"ARM {arm.get('arm_code', '')} (a patient needs one arm):")
                show(arm["match"], 1)
    if ctml.get("gene_role_dropped"):
        out.append(f"genes not required (information only): {ctml['gene_role_dropped']}")
    return out


def confirmations() -> dict[str, dict]:
    """The curator's latest decision per trial."""
    if not os.path.exists(CONFIRM_TSV):
        return {}
    out = {}
    for r in csv.DictReader(open(CONFIRM_TSV), delimiter="\t"):
        out[r["trial_id"]] = r
    return out


def record(trial_id, reviewer, verdict, effect, comment="", saw_ai=False) -> tuple[bool, str]:
    if trial_id not in audit_rows():
        return False, f"{trial_id} is not in {AUDIT_TSV}"
    if not (reviewer or "").strip():
        return False, "a reviewer name is required"
    if verdict not in VERDICTS:
        return False, "choose correct, error or borderline"
    if verdict == "error" and effect not in EFFECTS:
        return False, "an error needs its effect: loses, over-match or both"
    ai = audit_rows()[trial_id]
    new = not os.path.exists(CONFIRM_TSV)
    with open(CONFIRM_TSV, "a", newline="") as handle:
        w = csv.writer(handle, delimiter="\t", lineterminator="\n")
        if new:
            w.writerow(COLUMNS)
        w.writerow(
            [
                datetime.date.today().isoformat(),
                trial_id,
                reviewer.strip(),
                verdict,
                effect if verdict == "error" else "",
                "yes" if saw_ai else "no",
                ai["verdict"],
                ai["effect"],
                " ".join((comment or "").split()),
            ]
        )
    return True, f"{trial_id}: recorded {verdict}{' / ' + effect if verdict == 'error' else ''}"


def _loses(r):
    return r["verdict"] == "error" and r["effect"] in ("loses", "both")


def summary() -> dict:
    """
    Agreement and curator-confirmed rates, stratified by the AI verdict:
    each stratum's curator rate is weighted by its size in the audit.
    """
    rows, done = audit_rows(), confirmations()
    sizes = {s: sum(1 for r in rows.values() if stratum(r) == s) for s in VERDICTS}
    by = {s: [done[t] for t in done if stratum(rows[t]) == s] for s in VERDICTS}
    total = sum(sizes.values())

    def estimate(test):
        p_sum, var = 0.0, 0.0
        for s, n_s in sizes.items():
            got = by[s]
            if not got:
                if n_s:
                    return None  # a stratum with no confirmation yet: no estimate
                continue
            p = sum(1 for r in got if test(r)) / len(got)
            p_sum += n_s * p
            fpc = 1 - len(got) / n_s
            var += n_s**2 * p * (1 - p) / len(got) * fpc
        p = p_sum / total
        half = 1.96 * math.sqrt(var) / total
        return p, max(0.0, p - half), min(1.0, p + half)

    # (curator gave the AI's verdict, curator also agreed on losing or not, decided)
    agree = {
        v: (
            sum(1 for r in by[v] if r["verdict"] == v),
            sum(1 for r in by[v] if r["verdict"] == v and _loses(r) == _loses(rows[r["trial_id"]])),
            len(by[v]),
        )
        for v in VERDICTS
    }
    return {
        "sizes": sizes,
        "confirmed": {s: len(by[s]) for s in VERDICTS},
        "to_do": len([t for t in sample() if t not in done]),
        "agree": agree,
        "error_rate": estimate(lambda r: r["verdict"] == "error"),
        "loses_rate": estimate(_loses),
        "saw_ai": sum(1 for r in done.values() if r.get("saw_ai") == "yes"),
    }


def summary_text() -> str:
    s = summary()
    lines = [
        f"Audit {AUDIT_TSV} against release {RELEASE}; confirmations in {CONFIRM_TSV}",
        f"confirmed so far: {s['confirmed']} of strata {s['sizes']} (sample still to do: {s['to_do']})",
    ]
    for v in VERDICTS:
        same, same_effect, n = s["agree"][v]
        if n:
            extra = f" ({same_effect} also on whether it loses patients)" if v == "error" else ""
            lines.append(f"  AI said {v}: curator agreed on {same} of {n}{extra}")
    for name in ("error_rate", "loses_rate"):
        e = s[name]
        label = "trials with an error" if name == "error_rate" else "trials losing patients"
        if e is None:
            lines.append(f"  {label}: no estimate until every stratum has a confirmation")
        else:
            lines.append(
                f"  {label}: {100 * e[0]:.0f}% (95% CI {100 * e[1]:.0f}-{100 * e[2]:.0f}%), curator-confirmed"
            )
    if s["saw_ai"]:
        lines.append(f"  {s['saw_ai']} decisions were made after seeing the AI verdict")
    return "\n".join(lines)
