"""
The JSON-schema machinery every prompt shares: the enum cap per platform and
its counters, keeping answers inside the candidate list (keep_candidates and
the off-list counters), and the fixed order candidate lists are printed in
(prompt_list, diagnosis_prompt_list).

The counters are module state and live only here.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.2).
"""

from loguru import logger

import config
import utils.llm.transport as transport


def prompt_list(values):
    """
    A list printed into a prompt, in a fixed order: sorted, duplicates removed.
    Used for gene lists; diagnosis candidates use diagnosis_prompt_list.

    Every candidate list and gene list reached the prompts in the order of
    the Python set it was built from, and that order follows PYTHONHASHSEED,
    which production does not pin. So one trial got differently ordered
    prompts on every run: a full-pipeline check with a stub model found the
    level-1 and both diagnosis prompts differing under seeds 0/1/2 on 7 of
    8 trials, and with only the gene order changed, 16 of 45 Haiku genomic
    answers changed. Every list printed into a prompt goes through here or
    through diagnosis_prompt_list.
    """
    return sorted({v for v in values if v is not None}, key=str)


def diagnosis_prompt_list(values):
    """
    Diagnosis candidates in a fixed shuffle: ordered by the SHA-256 of each
    name. The result is reproducible and independent of PYTHONHASHSEED.

    The order changes what the model answers, so it was measured: Haiku 4.5,
    the 50-trial diagnosis benchmark, 3 runs per order.

    | order | population recall | population precision | diagnoses |
    |---|---|---|---|
    | set order, seeds 0/1/2 | 0.934 / 0.937 / 0.938 | 0.784 / 0.810 / 0.796 | 343 / 309 / 325 |
    | alphabetical | 0.925 | 0.816 | 292 |
    | Oncotree tree order | 0.915 | 0.784 | 287 |
    | SHA-256 shuffle | 0.942 | 0.798 | 312 |

    Alphabetical and tree order lose recall. Both put related names next to
    each other; that the model then stops early inside a group is a guess,
    not measured. The shuffle
    behaves like the random orders every earlier measurement used, and it
    is no worse than them: recall +0.007 [-0.009, +0.031] paired per trial.
    Each name's position depends only on the name, so adding an Oncotree
    node does not reorder the rest.
    """
    import hashlib

    return sorted(
        {v for v in values if v is not None},
        key=lambda v: (hashlib.sha256(str(v).encode("utf-8")).hexdigest(), str(v)),
    )


# Self-hosted backends compile the schema into a generation grammar, and one
# with several hundred alternatives is slow to build. Above the cap the enum is
# dropped and the schema still guarantees well-formed JSON of the right shape.
# The cap depends on the backend - config.SCHEMA_ENUM_MAX_VALUES says why - and
# this is the fallback for a platform it does not list.
_DEFAULT_MAX_ENUM_VALUES = 400


# How often a candidate list was sent as an enum ("enum"), came near the cap
# ("near_cap") or was sent without its enum ("dropped"), for the run summary.
# Module state because the schema builders are plain functions called from
# deep inside the mapping path; reset_enum_cap_events() starts a new count.
ENUM_CAP_EVENTS = {"enum": 0, "near_cap": 0, "dropped": 0, "largest": 0}


def max_enum_values():
    """
    The enum cap for config.LLM_PLATFORM; None means the enum is never dropped.
    A replay uses the recorded platform's cap, or its schemas would differ
    from the recorded ones and every capped call would miss.
    """
    caps = getattr(config, "SCHEMA_ENUM_MAX_VALUES", {}) or {}
    platform = str(
        getattr(transport._llm_platform, "recorded_platform", None)
        or getattr(config, "LLM_PLATFORM", "")
    ).lower()
    return caps.get(platform, _DEFAULT_MAX_ENUM_VALUES)


def reset_enum_cap_events():
    for k in ENUM_CAP_EVENTS:
        ENUM_CAP_EVENTS[k] = 0
    for k in OFF_LIST_EVENTS:
        OFF_LIST_EVENTS[k] = 0


# Answers checked against, and dropped from, their call's candidate list;
# see keep_candidates.
OFF_LIST_EVENTS = {"checked": 0, "recased": 0, "kept_for_review": 0, "dropped": 0}


# trial id -> Oncotree names answered off-list; read and cleared by
# TrialMapManager, which records them as diagnosis_off_list and routes the
# trial to review.
OFF_LIST_BY_TRIAL = {}


def keep_candidates(result, allowed, trial_id="", extra=(), keep_valid=True):
    """
    A result that is not an object with an oncotree_diagnoses list (a
    malformed answer, or {} from text that did not parse) becomes
    {"oncotree_diagnoses": []}: no diagnosis from this call, rather than an
    exception downstream that loses the trial (full run 2026-09-25).

    Keep only diagnosis answers that were on the call's candidate list.

    The enum in the schema is what makes an off-list answer impossible on a
    grammar-compiling backend. On Anthropic the forced tool call is not
    `strict`, so the enum only guides the model, and an off-list answer
    reaches the pipeline. filter_diagnoses later drops a term that is not an
    Oncotree name ("Lymphoma", once per replicate on NCT02332668). But an
    Oncotree name from outside the branch the call offered passes it, and
    that is the wrong-branch error the candidate list exists to prevent. So
    the check is repeated here, in code, against exactly the list that was
    sent, whatever the backend.

    What happens to an off-list answer:
    - **Differs only in letter case:** rewritten to the candidate.
    - **Not an Oncotree name:** dropped.
    - **Valid Oncotree name from outside the offered list:** kept, recorded in
      OFF_LIST_BY_TRIAL, and the trial goes to review. Replaying the saved
      Haiku and Sonnet stage-2 runs (2,585 answers) found 4 off-list
      answers. Three were "Lymphoma", which is not an Oncotree name. The one
      Oncotree name was "Neuroblastoma" on NCT03838042, which the text
      lists and the answer key holds; stage 1 had failed to offer its
      branch. Dropping such answers would remove correct diagnoses; review
      lets a curator decide.
    - **Level-1 calls (keep_valid=False):** an off-list answer is dropped even
      if it is a valid name, because the caller uses the answer as a branch
      key.

    Items are strings, or {"oncotree_value": ...} objects for the level-1
    schema. `extra` holds the values that schema also permits ("", "Other").
    """
    if not isinstance(result, dict) or not isinstance(result.get("oncotree_diagnoses"), list):
        # Callers index ["oncotree_diagnoses"] directly (the level-1 caller
        # does), so a malformed or empty answer must still have the key.
        return {**(result if isinstance(result, dict) else {}), "oncotree_diagnoses": []}
    permitted = {a for a in list(allowed) + list(extra) if a is not None}
    by_case = {}
    for a in permitted:
        by_case.setdefault(str(a).casefold(), []).append(a)
    kept = []
    for item in result["oncotree_diagnoses"]:
        value = item.get("oncotree_value") if isinstance(item, dict) else item
        OFF_LIST_EVENTS["checked"] += 1
        if value in permitted:
            kept.append(item)
            continue
        same = by_case.get(str(value).casefold(), []) if isinstance(value, str) else []
        if len(same) == 1:
            OFF_LIST_EVENTS["recased"] += 1
            logger.info(f"{trial_id} | diagnosis answer {value!r} recased to candidate {same[0]!r}")
            kept.append(dict(item, oncotree_value=same[0]) if isinstance(item, dict) else same[0])
            continue
        from utils.reference_validation import canonical_diagnosis

        name = canonical_diagnosis(value) if keep_valid and isinstance(value, str) else None
        if name:
            OFF_LIST_EVENTS["kept_for_review"] += 1
            OFF_LIST_BY_TRIAL.setdefault(trial_id, set()).add(name)
            logger.warning(
                f"{trial_id} | diagnosis answer {value!r} was not among the "
                f"{len(permitted)} candidates offered; kept, trial goes to review"
            )
            kept.append(item)
            continue
        OFF_LIST_EVENTS["dropped"] += 1
        logger.warning(
            f"{trial_id} | diagnosis answer {value!r} was not among the "
            f"{len(permitted)} candidates offered; dropped"
        )
    return dict(result, oncotree_diagnoses=kept)


def enum_cap_summary() -> str:
    e = ENUM_CAP_EVENTS
    return (
        f"Schema enums: {e['enum']} sent, {e['near_cap']} near the cap, "
        f"{e['dropped']} dropped over the cap ({max_enum_values()} on "
        f"{getattr(config, 'LLM_PLATFORM', '?')}); largest list {e['largest']}. "
        f"Diagnosis answers: {OFF_LIST_EVENTS['checked']} checked against their "
        f"candidate list, {OFF_LIST_EVENTS['recased']} recased, "
        f"{OFF_LIST_EVENTS['kept_for_review']} off-list kept for review, "
        f"{OFF_LIST_EVENTS['dropped']} dropped"
    )


def _one_of(allowed, extra=(), trial_id=""):
    """
    A string constrained to `allowed`, or an unconstrained one if too many.

    Dropping the enum used to be silent, and it is exactly the failure the
    enum exists to prevent: an off-list diagnosis becomes sayable again. It
    now logs a WARNING with the trial and size, and an INFO above
    config.SCHEMA_ENUM_NEAR_CAP_FRACTION of the cap. Measured 2026-09-24 on
    the two Haiku replicates of the 50-trial benchmark: the largest list sent
    was 370 (NCT02813135), p95 226, 2-3 calls above 320 and none above 400;
    across the 1,255 cached trials the seed floor alone reaches 438.
    """
    values = sorted({a for a in list(allowed) + list(extra) if a is not None})
    if not values:
        # An empty enum would make every answer invalid.
        return {"type": "string"}
    n = len(values)
    ENUM_CAP_EVENTS["largest"] = max(ENUM_CAP_EVENTS["largest"], n)
    cap = max_enum_values()
    if cap is not None and n > cap:
        ENUM_CAP_EVENTS["dropped"] += 1
        logger.warning(
            f"{trial_id} | {n} candidates exceed the schema enum cap of {cap} "
            f"on {config.LLM_PLATFORM}; enum dropped, off-list answers are "
            f"possible for this call"
        )
        return {"type": "string"}
    ENUM_CAP_EVENTS["enum"] += 1
    near = getattr(config, "SCHEMA_ENUM_NEAR_CAP_FRACTION", 0.8)
    if cap is not None and n > near * cap:
        ENUM_CAP_EVENTS["near_cap"] += 1
        logger.info(f"{trial_id} | {n} candidates, near the schema enum cap of {cap}")
    return {"type": "string", "enum": values}
