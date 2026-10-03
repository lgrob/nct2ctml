# Disease status is no longer published (2026-10-02)

- **Date:** 2026-10-02
- **Roadmap:** 3.4 follow-up
- **Outcome:** adopted: `PUBLISH_DISEASE_STATUS = False`; the model is no
  longer asked

**Question.** ClinicalTrials.gov trials got a `disease_status` criterion
(Untreated, Localized, Recurrent, Refractory, Advanced, ...) from a model
call, written beside the diagnosis:

```yaml
- clinical:
    age_numerical: <61
    disease_status: [Refractory, Recurrent, Advanced]
```

MatchMiner can satisfy that only from a disease status in the patient record.
Two things made the criterion a source of lost patients rather than a filter:
- **The patient side.** Kispi's patient records are not known to carry a
  reliable disease status. Where they carry none, every trial with the
  criterion is invisible to the patient, even when the model read the trial
  correctly; where the status is out of date, the trial is lost the same way.
- **The trial side.** The
  [2026-10-02 audit](../runs/2026-10-02-3.4-audit.md) found the model's
  status wrong in 7 of 60 sampled trials, all of them losing patients. For
  example NCT03314974, a transplant trial for patients in remission,
  published as Refractory/Recurrent; and NCT03500133, classical Hodgkin
  lymphoma of any stage, published as Early Stage.

**Method.** The gpt-oss corpus was replayed (from both runs' saved answers,
with the diagnosis text floor on) with the criterion off, and compared with
the same replay with it on: 1,133 trials (the 4 the user accepted that day
were no longer in the queue).
- **Trials carrying `disease_status`:** 802 before, 0 after.
- **Routing:** unchanged, 982 published, 151 in review.
- **Benchmark:** identical (NCT population recall 0.938, precision 0.681, gene
  F1 0.748, age F1 0.901). It does not score disease status, so it cannot show
  the gain.

**Decision.** Taken by the user. `config.PUBLISH_DISEASE_STATUS` defaults to
False:
- the mapper neither asks the model nor publishes the criterion, which saves
  one model call per NCT trial;
- CTIS never had it.

The cost is an over-match: a newly diagnosed patient also sees relapse-only
trials, which the treating physician dismisses from the trial text. No
patient is lost to the criterion any more.

Not changed:
- **The reviewed layer:** 21 of the 60 files in `ctml/reviewed` carried
  `disease_status`, put there or confirmed by a curator. On 2026-10-03 the
  user decided the patient-side argument applies to them as well, and it was
  removed from all 21.
  - The removal was textual, 81 lines, so each file keeps its layout.
  - Each file was checked to load as the same tree minus `disease_status`,
    with the `clinical` nodes it emptied dropped.
  - None of those nodes was an alternative under an `or`, so no match was
    narrowed.
- **Reversible:** if the patient data gains a reliable disease status,
  `NCT2CTML_PUBLISH_DISEASE_STATUS=true` restores the old behaviour for a run,
  and the decision can be revisited with a measurement against real patients.
