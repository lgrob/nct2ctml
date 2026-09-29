"""
The age prompt: both enrolment age bounds read from free text, each with its
unit and whether it is inclusive (CTIS publishes no structured age, and
ClinicalTrials.gov's maximum is ambiguous). utils/age_bounds turns the answer
into CTML.

Moved from utils/ai_helper.py on 2026-09-29 (step 11, phase 3.3).
"""

from inspect import cleandoc

import utils.llm.transport as transport


def get_age_bounds(trial_id: str, inclusion_criteria: str) -> dict:
    """
    Read the enrolment age range out of free-text criteria: both bounds, each
    with its unit and whether it is inclusive.

    CTIS publishes no structured age; ClinicalTrials.gov publishes one whose
    maximum is ambiguous between completed units and an exclusive bound. The
    text is too varied for a pattern ("Age >=1 and <80 years", "Patients aged
    1 to <=21 years", "Children between 1 year (>= 12 months) and 18 years")
    and contains ages that are not eligibility bounds at all, such as the
    Karnofsky/Lansky split at 16 years. The unit is returned as stated rather
    than converted, because the completed-units reading adds one unit of
    whatever the trial wrote. See utils/age_bounds.py for how the answer is
    used.
    """
    schema, prompt = get_age_bounds_prompt(inclusion_criteria)
    ai_response = transport.send_ai_request(trial_id, prompt, schema)
    return transport.parse_ai_response(ai_response, trial_id)


def get_age_bounds_prompt(inclusion_criteria):
    prompt = f"""Task: From the InclusionCriteria, find the age range a participant must be in to enrol.

        InclusionCriteria: {inclusion_criteria}

        Rules:
        - Report only limits on the participant's age at enrolment.
        - Ignore ages that are not eligibility limits: the age at which a
          different performance scale applies (Karnofsky vs Lansky), the age at
          original diagnosis when it differs from enrolment age, and ages in
          dosing, consent or assent text.
        - If different cohorts, parts or phases allow different ages, report the
          widest range across them: the lowest minimum and the highest maximum.
          Any one cohort admitting the participant is enough.
        - Report each number and unit exactly as written. Do not convert
          "18 months" to years.
        - inclusive is true when the limit itself is allowed: ">=", "at least",
          "or older", "<=", "or younger", "up to and including", and ranges such
          as "between 1 and 21 years" or "1-21 years". inclusive is false when
          the limit itself is excluded: "<", "under", "younger than", "less
          than", "older than", "before their 22nd birthday".
        - If no minimum (or no maximum) is stated, set its value to null.

        Output in JSON format:
        {{
        "minimum": {{"value": 1, "unit": "years", "inclusive": true}},
        "maximum": {{"value": null, "unit": "years", "inclusive": true}}
        }}
        where value is a number or null, and unit is one of years, months,
        weeks, days.
        """
    return AGE_BOUNDS_SCHEMA, cleandoc(prompt)


_AGE_BOUND_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": ["number", "null"]},
        "unit": {"type": "string", "enum": ["years", "months", "weeks", "days"]},
        "inclusive": {"type": "boolean"},
    },
    "required": ["value", "unit", "inclusive"],
}


AGE_BOUNDS_SCHEMA = {
    "type": "object",
    "properties": {"minimum": _AGE_BOUND_SCHEMA, "maximum": _AGE_BOUND_SCHEMA},
    "required": ["minimum", "maximum"],
}
