# A second reader: Claude Haiku 4.5 beside gpt-oss:120b (2026-10-20)

- **Date:** 2026-10-20
- **Roadmap:** follows [D1](2026-10-01-gpt-oss-backend.md); 3.4 follow-up
- **Outcome:** proposed, awaiting the user. gpt-oss:120b stays the mapping;
  Haiku 4.5 reads every trial a second time; a disagreement where the
  published mapping shuts out patients the second reader admits sends the
  trial to review (`TWO_READERS_ROUTE=narrows`).

**Question.** Does a second model, from another family, find the trials that
lose eligible patients, and at what review load?

The audits found about one published trial in four losing patients. Review
routing catches only part of them, because every routing rule so far is a
deterministic check on a known failure. A second reader is not a rule: it
disagrees wherever the two models read the text differently, whatever the
cause.

**The reproducibility argument is unchanged.** It is the reason gpt-oss is the
backend ([D1](2026-10-01-gpt-oss-backend.md)). The published CTML is still
gpt-oss's, from weights the project keeps. Haiku only decides which trials a
person reads. If the Haiku snapshot is retired, past flags stay in the files
and `runs/`, and a future run needs another second model. A different family
from the primary is the one requirement.

**Method.** `utils/two_readers.py` compares two mappings of a trial on who it
reaches:

- **Diagnoses** as the patients they reach (descendants expanded, `!`
  exclusions out).
- **Genes** as required or excluded.
- **Ages** as the numeric window.

Each difference is `narrows` (the published mapping shuts out patients the
second admits) or `widens`. Two tests, both scored by
`bench/two_readers_measure.py`:

1. **The 56 curated benchmark trials.** gpt-oss is the replay of run
   `20260930T200508Z-6e452d` (`bench/output-gpt-oss-120b-v3`); Haiku is the
   live run `20261020T114143Z-04720d`, on the same code. A mapping compared
   with the key by the same comparator gives its errors: `narrows` against
   the key loses patients.
2. **The third audit's 150 trials** (`ctml/audit_2026-10-03.tsv`), a random
   draw of published trials whose errors were found by reading the text, not
   by the key the pipeline was tuned against. Haiku read all 150 with the
   current code (run `20261020T140042Z-b06e17`, job 7374792, $5.03, 0 API
   errors), against the mapping the audit judged (release
   `index-2026.10.03`).

   The audited mapping is from `59756d1`, older code than Haiku's, and the
   fixes since have changed 18 of the 150 (artifact
   `audit_2026-10-03_vs_rebuild_905fd0d.tsv`). Some raw disagreement is
   therefore code, not reader. The **control** is the 126 trials the rebuild
   left unchanged: for those the audit verdict describes today's gpt-oss
   mapping exactly. This is the estimate for production, where both readers
   run the same code.

**Result.**

| | benchmark (56) | audit, all (150) | **audit, control (126)** |
|---|---|---|---|
| trials that lose patients | 18 | 34 | 16 |
| caught by review routing alone | 6 | 0 (all were published) | 0 |
| caught with the second reader, `narrows` | 16 (89%) | 26 (76%, 60-88%) | **10 (62%, 39-82%)** |
| caught with the second reader, `any` | 16 (89%) | 29 (85%, 70-94%) | 13 (81%, 57-93%) |
| review load, `narrows` | 52% | 32% (25-40%) | **22% (16-30%)** |
| review load, `any` | 71% | 45% | 38% (30-47%) |
| correct trials flagged, `narrows` | 2 of 15 | 10 of 59 | 10 of 59 (17%, 9-28%) |
| flagged trials that are audit errors, `narrows` | - | 32 of 48 (67%) | 15 of 28 (54%, 36-70%) |

Intervals are 95% Wilson.

- **The second reader finds patient-losing trials that nothing else finds.**
  Every losing trial in the audit sample had been published. On the control
  set, narrowing disagreements catch 10 of the 16 that remain.
- **Most of the added review lands on errors.** Of the 28 flagged control
  trials, 15 are audit errors (7 lose patients, 3 both, 5 over-match), 3 are
  borderline and 10 are correct. That is 17% of the trials the audit judged
  correct.
- **`narrows` is the better routing.** On the audit, `any` catches 3 more of
  the 16 losing control trials for 20 more reviews; the extra flags are
  mostly over-matches. On the benchmark both catch 16 of 18, and `any` costs
  11 more reviews. `config.TWO_READERS_ROUTE` now defaults to `narrows`. It
  only takes effect when the comparison is run.
- **The blind spot is small but real.** On the benchmark the two readers
  lose patients the same way, and agree, on 2 trials: NCT05748171 and
  NCT07215910. Both are key or pipeline questions, as the 2026-09-30
  zero-gene trials were.
- **The 8 audit losers that narrows routing misses** are mostly ones a
  deterministic check now covers or should:
  - NCT00107289 and NCT04796012, arm narrower than its step: now caught by
    010f877.
  - NCT04681417 and NCT05384626, an age made global from one cohort.
  - NCT06519682, MMR genes and "MSS" required together.
  - 2024-516914-39-00, NCT02727803 and NCT06789198, a named population
    missing in both readings.
- **A union of the two readers' diagnoses is not worth building.** On the
  benchmark it raises population recall from 0.968 (gpt-oss) and 0.975
  (Haiku) only to 0.978, and lowers precision to 0.652.

**Cost.** Haiku as the second reader costs $0.034 a trial on random
published trials, or about $38 for the 1,137 in-scope trials at list price
and about $19 through the Batch API, per full run. Incremental runs read only
the trials that changed. The binding cost is curator time (roadmap D4). At
the control load of 22% (16-30%), a full corpus run over the 985 published
trials sends about 220 (160-300) more to review. About half of them carry an
error the audit would count, and they come on top of the trials review
routing already holds.

**Not measured.**

- **Replicates.** One run of each model. Haiku at temperature 0 varied on 6
  of 50 trials between its own runs. Some disagreement is therefore Haiku's
  own noise, which inflates the load and leaves the sensitivity estimate
  roughly where it is.
- **Curator confirmation.** The audit verdicts are Claude's, checked by a
  second Claude reader, and await a curator (`/audit` in the review app).
- **CTIS** is underrepresented: 35 of the 150 audit trials, and the gpt-oss
  benchmark replay lacks the four newest CTIS keys.

**Decision for the user.**

1. **Adopt the second reader** with `narrows` routing on the next full run
   (`scripts/run_anthropic_mapping.sh reader` on the published corpus, then
   `python -m utils.two_readers --second <dir> --apply`).
2. **Or adopt it for the review queue only.** Run the comparison as a
   priority signal on trials already in review, without adding new ones,
   until curator time (D4) is settled.
3. **Or do not adopt.** Keep the deterministic checks as the only routing,
   and treat the 8 misses above as the next rules to write.
