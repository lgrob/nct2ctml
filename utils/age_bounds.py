"""
Age bounds read from eligibility prose, and how they combine with the
structured registry fields.

Both registries need this. CTIS publishes no structured age at all, so the
prose is the only source, and until now only its minimum was read - every
unreviewed CTIS trial was open-ended at the top. ClinicalTrials.gov publishes
minimumAge and maximumAge, but maximumAge is ambiguous: it is usually in
completed units ("17 Years" = until the 18th birthday), and about one sponsor
in three uses it as an exclusive bound instead ("3 Years" beside "birth to
age <3 years"). No arithmetic on the structured field fits both. The prose
says which, so it decides.

The model reads the prose (utils.ai_helper.get_age_bounds); everything here is
deterministic and offline, so the rules can be tested without a model. A
pattern was tried for the reading step and rejected - see src/ctis.py - so
this module deliberately does no text matching of its own.

The rules, and why:

- The structured minimum stays authoritative. It is exact, and there is no
  ambiguity for the prose to resolve.
- A structured maximum is narrowed from "<=N+1" to "<N" only when the prose
  states an EXCLUSIVE bound at the same N. That is the one case the prose
  settles. A prose bound that agrees with the completed-units reading, or
  disagrees in any other way, leaves the structured value alone: the wider
  reading was chosen deliberately, because an over-broad trial costs a
  clinician a minute and a narrow one silently withholds a trial.
- Prose fills a bound only where the structured field is empty.
- A prose minimum of zero is not a bound: it excludes nobody.
- Any failure of the reading step leaves the structured result unchanged.
  A model outage must never remove a bound.
"""
from loguru import logger

# Conversion to years for the units the prompt allows. Kept in step with
# src/clinical_trials_gov._AGE_UNIT_IN_YEARS, which covers the registry's
# structured field.
UNIT_IN_YEARS = {
    "years": 1.0,
    "months": 1.0 / 12.0,
    "weeks": 1.0 / 52.1775,
    "days": 1.0 / 365.25,
}

# Beyond this a value is a misreading (a date, a dose, a count), not an age.
_MAX_PLAUSIBLE_YEARS = 100.0
_SAME = 0.01  # years; two bounds this close are the same bound


def expression(operator, years):
    """A CTML age_numerical string: whole years as integers, else 2dp."""
    years = round(years, 2)
    if years == int(years):
        return f"{operator}{int(years)}"
    return f"{operator}{years}"


def _bound_years(bound, completed_units):
    """
    (years, inclusive) for one bound from the model, or None.

    `completed_units` applies to an inclusive maximum: "21 years or younger"
    admits a patient until their 22nd birthday, so one unit is added in the
    unit the trial stated - a month for "<= 18 months", not a year.
    """
    if not isinstance(bound, dict):
        return None
    value, unit = bound.get("value"), bound.get("unit")
    if value is None or unit not in UNIT_IN_YEARS:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    inclusive = bool(bound.get("inclusive", True))
    if completed_units and inclusive:
        value += 1
    years = value * UNIT_IN_YEARS[unit]
    if not 0 <= years <= _MAX_PLAUSIBLE_YEARS:
        return None
    return years, inclusive


def prose_bounds(result, trial_id=""):
    """
    (minimum, maximum) as CTML expressions from the model's answer, each
    None when absent or unusable.

    An inclusive maximum is emitted as "<N+1 unit>" - see _bound_years - and
    an exclusive one as "<N". A range whose minimum exceeds its maximum is a
    misreading and both ends are dropped.
    """
    result = result or {}
    low = _bound_years(result.get("minimum"), completed_units=False)
    high = _bound_years(result.get("maximum"), completed_units=True)
    if low and high and low[0] >= high[0]:
        logger.warning(f"{trial_id} | Prose age range is inverted ({result}); ignoring it")
        return None, None
    # "Birth to 21 years" states a minimum of zero, which excludes nobody.
    # Emitting ">=0" adds a criterion that selects nothing and disagrees with
    # every curated key that, rightly, leaves the bound out.
    if low and low[0] == 0 and low[1]:
        low = None
    minimum = expression(">=" if low[1] else ">", low[0]) if low else None
    maximum = None
    if high:
        maximum = expression("<", high[0])
    return minimum, maximum


def stated_exclusive_maximum(result):
    """The prose maximum in years if it is stated as exclusive, else None."""
    bound = (result or {}).get("maximum")
    parsed = _bound_years(bound, completed_units=False)
    if parsed and not parsed[1]:
        return parsed[0]
    return None


def reconcile_with_structured(structured_minimum, structured_maximum,
                              stated_maximum_years, prose, trial_id=""):
    """
    The trial's age bounds, structured fields first, prose where it decides.

    `structured_minimum` / `structured_maximum` are the expressions the
    registry fields map to on their own (the maximum already in the
    completed-units reading); `stated_maximum_years` is the maximumAge value
    as stated, before that reading. `prose` is the model's answer or None.
    Returns the list of expressions, lower first.
    """
    prose_minimum, prose_maximum = prose_bounds(prose, trial_id) if prose else (None, None)

    minimum = structured_minimum or prose_minimum
    if not structured_minimum and prose_minimum:
        logger.info(f"{trial_id} | No structured minimum age; using the prose bound {prose_minimum}")

    maximum = structured_maximum
    if structured_maximum and stated_maximum_years is not None:
        exclusive = stated_exclusive_maximum(prose) if prose else None
        if exclusive is not None and abs(exclusive - stated_maximum_years) < _SAME:
            maximum = expression("<", stated_maximum_years)
            logger.info(
                f"{trial_id} | Prose states the maximum age as exclusive; "
                f"{structured_maximum} narrowed to {maximum}")
        elif prose_maximum and prose_maximum != structured_maximum and exclusive is None:
            logger.debug(
                f"{trial_id} | Prose maximum {prose_maximum} differs from the structured "
                f"{structured_maximum}; keeping the structured reading")
    elif not structured_maximum and prose_maximum:
        maximum = prose_maximum
        logger.info(f"{trial_id} | No structured maximum age; using the prose bound {maximum}")

    return [b for b in (minimum, maximum) if b]


def read_age_bounds(trial_id, inclusion_text):
    """
    The model's reading of the age sentence, or None on any failure.

    None is safe everywhere this is used: callers fall back to the structured
    fields, which is exactly the behaviour before prose was read at all.
    """
    if not (inclusion_text or "").strip():
        return None
    try:
        import utils.ai_helper as ai
        result = ai.get_age_bounds(trial_id, inclusion_text)
    except Exception as e:
        logger.warning(f"{trial_id} | Age reading failed ({e}); using structured ages only")
        return None
    return result if isinstance(result, dict) else None
