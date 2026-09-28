# Measured: does a larger Claude model map more correctly?

- **Date:** 2026-09-24
- **Roadmap:** -
- **Outcome:** not adopted: Haiku 4.5 stays; neither larger model improves recall
- Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the text is unchanged.

Haiku 4.5, Sonnet 5 and Opus 5.5 were run on the production diagnosis path
over the 50 curated NCT trials, and on the gene and age prompts over the 55
reviewed trials. Each ran two replicates at commit 1d29981; there were 0
failed calls and every answer came back through the tool. Each model got the
request shape the API accepts for it: Sonnet 5 rejects `temperature`, and
Opus 5.5 rejects disabled thinking and a forced tool choice. The arm-criteria
split was frozen from Haiku, so this measures the diagnosis stage only, not
the split.

|  | Haiku 4.5 | Sonnet 5 | Opus 5.5 |
|---|---|---|---|
| diagnosis population recall | 0.935 | 0.926 | 0.914 |
| diagnosis population precision | 0.781 | 0.819 | 0.823 |
| diagnosis name F1 | 0.723 | 0.822 | 0.756 |
| diagnoses emitted (155 curated) | 342 | 288 | 259 |
| gene F1 | 0.639 | 0.632 | 0.651 |
| age F1 | 0.908 | 0.916 | 0.875 |
| relative cost | 1x | ~2x | ~4.5x |

Paired per trial against Haiku, with 95% bootstrap intervals:
- **Recall:** neither larger model improves it (Sonnet -0.009 [-0.040,
  +0.013], Opus -0.021 [-0.059, +0.006]).
- **Precision:** Sonnet's gain is the only clear effect, name F1 +0.10
  [0.04, 0.16].
- **Genes:** no difference.
- **Ages:** Opus is worse on 3 trials.

Haiku at temperature 0 still differed between replicates on 6 of 50 trials.
Decision: Haiku 4.5 stays; recall comes first, and neither larger model
improves it. Sonnet's precision gain is the bar for the stage-2 prompt work
(roadmap 2.4). Harness and caches: model_compare_harness.tar.gz and the
per-run caches, kept outside the repo.
