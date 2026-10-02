# Runs

Full mapping runs, targeted re-maps and review-queue audits, oldest first:
what ran, on what, and what came out. A run that led to a choice between
alternatives also has a file in [../decisions/](../decisions/).

| Date | Roadmap | Run |
|---|---|---|
| 2026-09-24 | 3.1 | [Dry run of the production map path (roadmap 3.1); H3 HGVS one-letter changes accepted](2026-09-24-3.1-dry-run.md) |
| 2026-09-25 | 3.2 | [Full run (roadmap 3.2), 2026-09-25](2026-09-25-3.2-full-run.md) |
| 2026-09-26 | - | [Existing output checked for exclusion-only diagnoses (2026-09-26)](2026-09-26-exclusion-only-diagnoses-check.md) |
| 2026-09-27 | - | [Six systematic issues from a 10-trial queue review (2026-09-27)](2026-09-27-queue-review-10-trials.md) |
| 2026-09-27 | - | [Second queue review: 20 trials (2026-09-27)](2026-09-27-queue-review-20-trials.md) |
| 2026-09-27 | - | [Targeted re-map of the review queue (2026-09-27)](2026-09-27-targeted-remap-review-queue.md) |
| 2026-09-28 | 3.2 | [Second full mapping run (roadmap 3.2, 2026-09-28)](2026-09-28-3.2-second-full-run.md) |
| 2026-09-28 | 7.7 | [Re-map of the 17 trials split at the wrong heading (roadmap 7.7, 2026-09-28)](2026-09-28-7.7-remap-17-trials.md) |
| 2026-09-30 | - | [Benchmark: qwen3.6:27b and gpt-oss:120b on Ollama (2026-09-30)](2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md) |
| 2026-10-02 | 3.2 | [First full mapping run with gpt-oss:120b (roadmap 3.2, 2026-10-02)](2026-10-02-3.2-gpt-oss-full-run.md) |
| 2026-10-02 | 3.4 | [Audit of the gpt-oss mapping run (roadmap 3.4, 2026-10-02)](2026-10-02-3.4-audit.md) |
| 2026-10-02 | 3.4 | [Second audit: the pipeline after the text floor and without disease status (2026-10-02)](2026-10-02-3.4-audit-2.md) |

## Recording a new one

Name the file `YYYY-MM-DD-<roadmap step>-<short-name>.md`. The two full runs
are the template. Record:

- **Inputs:** the commit, the registry cache date or pull, the trial set,
  the model, and the `run_id` (`runs/<run_id>/run.json` holds the rest).
- **Result:** coverage, calls and cost, what went to review and why, and the
  index counts.
- **Defects found** and where they were fixed, and what was **not done**.

Keep `runs/<run_id>/` from the repository root alongside: it is the only copy
of what the model answered.
