# Which model makes the audit first pass (2026-09-29)

**Question.** The 3.4 audit's first pass (doc/runs/2026-09-29-3.4-audit.md) ran on
claude-sonnet-5 and its flags were 70% real when checked against the text. Would a
different, larger model resolve more of them?

**Measured.** The same 60-trial prompts re-run on claude-opus-5, scored on the 20
trials where a human-checked verdict exists (all 10 with a high-confidence
screening-effect flag, plus 10 of the other 20 drawn with seed 20260929). Same
prompt, same tool schema, same context; only the model differs.

| | trials flagged | real | borderline | false positive | precision (real) |
|---|---|---|---|---|---|
| claude-sonnet-5 | 20 of 20 | 14 | 2 | 4 | 70% |
| claude-opus-5 | 18 of 20 | 14 | 1 | 3 | 78% |

- **Both models flag every one of the 14 confirmed errors.** Neither missed one.
- Opus is quieter: 39 issues against 47, and it drops two trials the Sonnet pass
  flagged only on borderline or context grounds.
- **Opus repeats 3 of the 4 false positives**, including NCT05745623, where
  `_SOLID_` was read as missing the trial's CNS population although it expands to
  651 codes of which 67 are CNS. That failure is missing context, not weak
  reasoning: the checker sees the wildcard, not the expansion.

**Outcome.** Not worth a model change on its own: +8 points of precision on n=20
(the interval is far wider than the gap) and the same context-driven false
positives. The cheaper fix is to give the checker what the index already knows -
the expanded diagnosis list rather than the raw wildcard, the union across arms,
and the fact that the index carries no HLA or surface-marker field. Do that before
paying for a larger auditor.

Two limits of this measurement: the 20 trials are the ones the Sonnet pass flagged,
so they are enriched for flags and "flagged 20 of 20" is true by construction; and
neither model's false-negative rate is measured, because no ground truth exists for
the trials neither flagged.

**Keep the auditor different from the mapper.** Mapping is Haiku 4.5; the audit runs
a larger model on the same text, which is the point of the pass. Record the auditor
model in the audit note, as doc/runs/2026-09-29-3.4-audit.md does.

## Per-trial

| trial | verdict after reading the text | sonnet-5 | opus-5 |
|---|---|---|---|
| 2024-519320-24-00 | false_positive | flag | - |
| 2024-520436-15-00 | real | flag | flag |
| NCT02446431 | real | flag | flag |
| NCT02508038 | real | flag | flag |
| NCT03314974 | real | flag | flag |
| NCT03630991 | real | flag | flag |
| NCT04072042 | real | flag | flag |
| NCT04217512 | real | flag | flag |
| NCT04616560 | real | flag | flag |
| NCT05292664 | false_positive | flag | flag |
| NCT05745623 | false_positive | flag | flag |
| NCT06031688 | false_positive | flag | flag |
| NCT06113809 | borderline | flag | - |
| NCT06411821 | real | flag | flag |
| NCT06529250 | borderline | flag | flag |
| NCT07070219 | real | flag | flag |
| NCT07070323 | real | flag | flag |
| NCT07106892 | real | flag | flag |
| NCT07188441 | real | flag | flag |
| NCT07262489 | real | flag | flag |
