# Six systematic issues from a 10-trial queue review (2026-09-27)

- **Date:** 2026-09-27
- **Roadmap:** -
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

A stratified random sample of 10 queued trials, checked against the text:
13 flags raised, 5 correct, 8 false alarms; 12 unflagged problems in 9 of 10
trials. Six causes, each measured over the index:

| | issue | measured | done |
|---|---|---|---|
| S4 | NCT split cut at 'inclusion and exclusion criteria' in running text | 18 in-scope trials | fixed (`exclusion_heading`); the 17 non-reviewed trials need a re-map |
| S3 | diagnosis text matching knew only Oncotree names | 1,785 -> 2,240 of 5,387 diagnosis uses found in their text | `ref/diagnosis_text_terms.tsv` + plurals; exclusion check moved 31 mapped trials to review (11/12 sampled real) |
| S5 | gene notation '(IDH) 1/2', '(CDKN)2A/B'; stale flags | scan changes in 1 of 1,255 trials; 13 of 84 queue flags stale | `join_bracketed_stems`; `clear-stale-gene-flags` (single-arm only) |
| S2 | unqualified ALL mapped to B-ALL only | 28 trials without any lineage wording | T-ALL added beside B-ALL, in the mapper and `fix-all-lineage` |
| S1 | cohort-specific genetics required trial-wide | rule 'gene in some cohort sections, required by every arm': 6 flags, 2 real | **not added**: "Phase 1:" also heads ordinary criteria; curator work |
| S6 | re-map guard held correct drops | 12 of 56 held drops exclusion-named; 2 scoped to randomisation | `resolve-remap-drops` with a scope guard: 10 drops, 5 trials back to mapped |

Index after all six: 935 mapped, 145 needs-review, 56 reviewed.
