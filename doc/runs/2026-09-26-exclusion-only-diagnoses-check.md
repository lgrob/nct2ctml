# Existing output checked for exclusion-only diagnoses (2026-09-26)

- **Date:** 2026-09-26
- **Roadmap:** -
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

`review_helper flag-exclusions --apply` was run at the user's request: 62
mapped trials moved to the review queue with diagnosis_excluded. The dry run
listed 69; 7 of them already have a curated copy in ctml/reviewed, which is
what the index publishes, so their machine copies were put back.
flag-exclusions now skips reviewed and out-of-scope trials. The review queue
and the audit pool leave out trials the index does not publish.

Index: 1,147 trials: 946 mapped, 145 needs-review, 56 reviewed. Queue by flag:
- diagnosis_excluded 67
- gene_unsupported 52
- diagnosis_off_list 16
- no diagnosis 15
- protein_change_unverified 3
- 2 edited and ready to accept
