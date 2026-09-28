# Genes kept out of the match tree are published, not queued (2026-09-28)

- **Date:** 2026-09-28
- **Roadmap:** 2.9, option A
- **Outcome:** adopted: published as genes_not_required, not queued
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

User decision (option A). gene_role_dropped no longer routes a trial to
review and no longer blocks accept: a gene kept out can only widen
matching, never lose a patient. The genes are published per trial in
trials.tsv as genes_not_required ("FLT3 (cohort_specific); ...") and shown
on review sheets as information. Cost: about 10 of 289 labelled every-patient
requirements are kept out in the 2.9 measurement, so those trials over-match,
visibly. Keeps about 140 trials out of the review queue that roles alone
would have added. 543 tests pass.
