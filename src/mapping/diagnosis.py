"""
The diagnosis path both registries share: the trial's own conditions read as
a floor (seed_and_map_diagnosis), the two-stage Oncotree mapping of the
eligibility text, the _SOLID_/_LIQUID_ basket rule, and the text the
diagnosis step is given (diagnosis_text, per config.DIAGNOSIS_INPUT).

Moved from src/clinical_trials_gov.py on 2026-09-29 (step 11, phase 2).
"""

from loguru import logger

import src.trial_data_helper as tdh
import utils.llm.prompts.diagnosis as dx_prompts
import utils.oncotree as onct
import utils.reference_validation as rv


def map_eligibility_criteria_to_oncotree_term(
    nct_id: str, eligibility_criteria: str, seed_terms=()
) -> list:
    """
    Two-stage mapping: pick level_1 nodes, then pick children within them.

    `seed_terms` are Oncotree terms already known to apply - typically read
    straight out of the trial's own conditions - and their branches are added
    to the second stage no matter what the first stage chose. Without that
    floor a wrong level_1 makes the right answer unreachable rather than
    merely unlikely: neuroblastoma sits under Peripheral Nervous System, but
    it arises in the adrenal medulla, so "Adrenal Gland" is the natural pick
    and its only children are Adrenocortical Adenoma, Adrenocortical Carcinoma
    and Pheochromocytoma. Five of six neuroblastoma trials in the benchmark
    returned exactly that pair, with no error raised.
    """
    level_1_diagnosis, l1_to_all_mapping = onct.get_all_oncotree_data()
    level1_oncotree_values_dict = dx_prompts.get_oncotree_diagnoses_from_trial_info(
        nct_id, eligibility_criteria, level_1_diagnosis
    )
    level1_diagnoses = level1_oncotree_values_dict.get("oncotree_diagnoses", [])

    all_level_oncotree_values = set()
    all_possible_diagnoses = set()
    for item in level1_diagnoses:
        if item == "" or item.lower() == "other":
            continue
        child_oncotree_values = l1_to_all_mapping[item]
        all_level_oncotree_values.update(child_oncotree_values)

    seed_terms = {t for t in (seed_terms or ()) if t}
    forced = {parent for parent, children in l1_to_all_mapping.items() if seed_terms & children}
    for parent in forced:
        all_level_oncotree_values.update(l1_to_all_mapping[parent])
    if forced:
        logger.info(
            f"NCTID: {nct_id} | Forcing {sorted(forced)} into the child-level "
            f"list; the trial names {sorted(seed_terms)} outright"
        )

    logger.debug(
        f"NCTID: {nct_id} | Diagnoses = {level1_diagnoses}. Child values = {all_level_oncotree_values}"
    )
    if not all_level_oncotree_values:
        logger.debug(
            f"NCTID: {nct_id} | No child oncotree values to map, skipping child-level diagnosis request"
        )
        return []

    oncotree_diagnoses_result = dx_prompts.get_oncotree_diagnoses_from_trial_info(
        nct_id, eligibility_criteria, all_level_oncotree_values
    )
    if oncotree_diagnoses_result and "oncotree_diagnoses" in oncotree_diagnoses_result.keys():
        all_possible_diagnoses.update(oncotree_diagnoses_result["oncotree_diagnoses"])
    return sorted(all_possible_diagnoses)


# How many umbrella conditions mean "any malignancy qualifies" rather than
# "here is a heading for my list". See _basket_wildcards.
_BASKET_BROAD_TERMS = 2


def _basket_wildcards(conditions_list, nct_id: str = "") -> set:
    """
    The MatchMiner wildcards this trial's conditions justify, if any.

    A broad condition alone is not enough. Registries routinely file a
    category header beside the actual diagnoses: NCT04775485 lists
    "Advanced Solid Tumor" next to "Low-grade Glioma", and NCT04897321 puts
    "Pediatric Solid Tumor" ahead of osteosarcoma, rhabdomyosarcoma,
    neuroblastoma, Ewing sarcoma and Wilms tumour. Reading those as baskets
    throws away a precise answer and replaces it with _SOLID_, which matches
    every solid-tumour patient in the database - the failure a clinician
    notices as noise and a curator never sees.

    31 of the 104 cached trials whose conditions contain a broad term also
    name a specific Oncotree diagnosis, so this is not a corner case.

    The broad term therefore wins when the trial names nothing specific -
    NCT02813135's sole condition is "Pediatric Cancer" - or when it registers
    two or more umbrella terms.

    That second case is the one this rule missed at first. A registry lists
    *one* umbrella term as a header for its list, so "Pediatric Solid Tumor"
    ahead of fifteen paediatric solid tumours is a header. A trial that
    registers several different ways of saying "any malignancy" is not
    heading a list, it is describing an unrestricted population: NCT07440290
    (tumour-agnostic dabrafenib) registers "Malignant Neoplasm", "Cancer" and
    "Solid Tumour" among twenty conditions, and reading its two resolvable
    ones as the answer produced 55 diagnoses where the curated answer is
    _SOLID_ + _LIQUID_.

    The threshold is a heuristic fitted to a handful of trials. NCT06607692
    restates one umbrella twice ("Solid Tumor Cancer", "Solid Tumor
    Refractory to Conventional Treatment") beside six named tumours, and was
    filed here as an over-reach. Its inclusion criteria say otherwise -
    "relapsed/refractory solid tumours with positive uptake on SSTR-PET" - so
    the named tumours are examples and the basket reading is right. On
    2026-09-23 the inclusion criteria of all 12 cached trials where this rule
    and a specific seed both fire were read by hand, and each describes a
    basket: a tumour-agnostic alteration (the four DETERMINE arms,
    NCT04585750), "solid malignancy or lymphoma" (NCT02332668), any
    histology of solid tumour (NCT03465592, NCT04222413, NCT06607692,
    NCT06721689), or a
    solid-tumour part alongside diagnosis-restricted parts (NCT05468359,
    NCT06636435). If it does over-reach, that direction is the tolerable
    one - a wildcard is one over-broad criterion a clinician dismisses in a
    moment.
    """
    broad_any = tdh.all_tumours(conditions_list)
    broad_solid = tdh.all_solid_tumours(conditions_list)
    if not (broad_any or broad_solid):
        return set()

    named = rv.diagnoses_from_conditions(conditions_list)
    broad_terms = [
        c for c in (conditions_list or []) if tdh.all_tumours([c]) or tdh.all_solid_tumours([c])
    ]
    if named and len(broad_terms) < _BASKET_BROAD_TERMS:
        logger.info(
            f"NCTID: {nct_id} | Conditions contain a broad term but also name "
            f"{sorted(named)}. Treating the broad term as a category header, "
            f"not a basket, and mapping the specific diagnoses instead."
        )
        return set()
    if named:
        logger.info(
            f"NCTID: {nct_id} | Conditions name {sorted(named)} but register "
            f"{len(broad_terms)} umbrella terms {broad_terms}. Reading the "
            f"specific ones as examples and the trial as a basket."
        )

    return {"_SOLID_", "_LIQUID_"} if broad_any else {"_SOLID_"}


def diagnosis_text(
    inclusion: str, exclusion: str, title: str = "", conditions=(), legacy: str = ""
) -> str:
    """
    The text the diagnosis step is given, per config.DIAGNOSIS_INPUT, for
    both registries and for arm-level criteria. `legacy` is the caller's
    old text, returned unchanged in legacy mode so its prompts (and cached
    answers) stay byte-identical.
    """
    import config

    mode = getattr(config, "DIAGNOSIS_INPUT", "legacy")
    head = []
    if title:
        head.append(f"Title: {title}")
    if conditions:
        head.append("Conditions: " + "; ".join(c for c in conditions if c))
    if mode == "inclusion_only":
        parts = head + (
            [f"Inclusion Criteria: {inclusion.strip()}"] if (inclusion or "").strip() else []
        )
        return "\n".join(parts).strip()
    if mode == "labelled":
        parts = head
        if (inclusion or "").strip():
            parts = parts + [f"Inclusion Criteria: {inclusion.strip()}"]
        if (exclusion or "").strip():
            parts = parts + [f"Exclusion Criteria: {exclusion.strip()}"]
        return "\n".join(parts).strip()
    return legacy


def seed_and_map_diagnosis(trial_id: str, conditions_list, eligibility_criteria: str = ""):
    """
    The diagnosis path both registries share: read the conditions, then ask
    the model with them as a floor. Returns (seeded, from_eligibility).

    Factored out because ClinicalTrials.gov and CTIS had drifted apart.
    src/ctis.py called map_eligibility_criteria_to_oncotree_term directly with
    no seed, so 331 cached CTIS trials - a quarter of the corpus - got none of
    this: no deterministic floor, no branch forcing, and no warning when the
    model failed to return a diagnosis the trial names outright. What differs
    between the two registries is only the fallback when this returns nothing,
    so that stays with each caller.

    `seeded` includes `_SOLID_`/`_LIQUID_` when the conditions describe a
    basket, alongside any specific terms they name. The model is still
    handed only the Oncotree terms.
    """
    # Read the trial's own condition list first. It costs no tokens, cannot
    # hallucinate, and on the curated benchmark a plain lookup of these strings
    # against Oncotree now scores above what the 70B model achieves through
    # both LLM stages. It is still a floor rather than a replacement: precision
    # is high but it finds about two thirds of the answers.
    seeded = rv.diagnoses_from_conditions(conditions_list, trial_id)
    if seeded:
        logger.info(f"{trial_id} | Conditions name Oncotree terms directly: {seeded}")

    from_eligibility = []
    if eligibility_criteria and eligibility_criteria.strip():
        logger.info(f"{trial_id} | Mapping global diagnosis from eligibility criteria")
        from_eligibility = map_eligibility_criteria_to_oncotree_term(
            trial_id, eligibility_criteria, seeded
        )
        # Worth seeing. The model disagreeing with a string the trial states
        # outright is the signature of the branch problem above, and it was
        # silent until now.
        overlooked = set(seeded) - set(from_eligibility)
        if overlooked:
            logger.warning(
                f"{trial_id} | Eligibility mapping did not return {sorted(overlooked)}, "
                f"which the trial's own conditions name outright. Kept from the conditions."
            )

    # A basket is a basket whatever else the conditions name. The wildcards
    # used to be reached only when nothing specific was found, so a
    # tumour-agnostic trial that also lists a few entities kept the entities
    # and lost the basket: NCT02332668 (KEYNOTE-051, "solid malignancy or
    # lymphoma") and NCT07440290 (tumour-agnostic BRAF V600) reached 2% and 3%
    # of the patients their curated keys do. The union, not a replacement:
    # NCT02332668's rule yields _SOLID_ alone, and dropping the Classical
    # Hodgkin Lymphoma it names would remove the trial from every lymphoma
    # patient. Added after the model call, because the floor handed to the
    # model must be Oncotree nodes and the wildcards are not.
    wildcards = sorted(_basket_wildcards(conditions_list, trial_id) - set(seeded))
    if wildcards:
        logger.info(f"{trial_id} | Conditions describe a basket; adding {wildcards}")
        seeded = list(seeded) + wildcards
    return seeded, from_eligibility


def basket_wildcards(conditions_list, trial_id: str = "") -> set:
    """Public name for the basket rule, so CTIS need not reach for a private one."""
    return _basket_wildcards(conditions_list, trial_id)
