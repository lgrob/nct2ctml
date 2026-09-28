# Targeted re-map of the review queue (2026-09-27)

- **Date:** 2026-09-27
- **Roadmap:** -
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

At the user's request the review queue was re-mapped at b3d0c9c, so it
carries all fixes since the full run: labelled diagnosis input, the blocked
aliases, the histone and notation change, and the scope rules. The queue
held 175 trials after flag-unsupported-genes --apply moved 34 mapped
trials in. 4 trials with curator edits were left as they were, so 171 were
re-mapped. The run used Haiku 4.5 through the analysis environment, as the
full run did: 866 new calls, the rest answered from the full-run cache.

Recall first. A re-mapped trial is published as mapped only if every
patient code it loses against its previous version comes from a diagnosis
that the exclusion text names (and the inclusion text does not).
Otherwise it goes to review with remap_dropped_diagnoses, which the review
sheet shows with the text that names each diagnosis. The previous version
is kept as .yaml.prev. This held back 22 of the 80 trials the re-map would
have published, among them:
- NCT04329728, which lost AML;
- NCT04640987, which lost B-ALL;
- NCT06514313, which lost non-RMS sarcoma;
- 2024-515499-12-00, which lost MPAL, although its inclusion text names it.
Some held back are correct drops the check cannot see. For example,
NCT04166409 states "Patients with ependymoma are not eligible" inside its
inclusion criteria.

Result: 58 trials published as mapped; the queue went from 175 to 117.
Flags on the re-mapped trials: diagnosis_excluded 67 -> 30,
gene_unsupported 84 -> 44, diagnosis_off_list 16 -> 11, plus 38
remap_dropped_diagnoses. Index: 963 mapped, 117 needs-review, 56 reviewed,
0 conflicts.
