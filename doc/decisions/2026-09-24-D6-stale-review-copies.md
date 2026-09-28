# Stale review copies are kept and reported (roadmap 3.0, decision D6)

- **Date:** 2026-09-24
- **Roadmap:** 3.0, D6
- **Outcome:** adopted: keep the review copy, publish it, report the conflict
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

A trial routed to `ctml/needs-review` by one run and mapped cleanly by a
later one kept its review copy, and the index published it without saying
so. The decision, from the user: keep the copy and report the conflict,
rather than delete it (a curator may be editing it) or let the newer file
win.
- **Mapper:** it leaves the review copy in place and logs a WARNING when a
  clean mapping lands beside one.
- **Index:** it still publishes the review copy, but sets `trials.tsv`
  `layer_conflict = newer_mapped_copy`, lists both files with their
  modification times in the new `layer_conflicts.tsv`, and counts them in
  the manifest.
- **What is not a conflict:** an older mapped copy under a review copy (the
  last run flagged the trial) and a reviewed copy over newer machine output.
- **Limit:** "newer" is the file modification time, because the CTML
  records no mapping time.

On the current layers: 0 conflicts (`ctml/needs-review` is empty).
`trial_diagnosis.tsv` and `trial_genomic.tsv` are byte-identical; `trials.tsv`
gains one column. 413 tests pass offline; 2 live-model tests are opt-in.
