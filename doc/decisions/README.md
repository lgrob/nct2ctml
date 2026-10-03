# Decisions

One file per decision taken on measurements or by the user, oldest first. A
decision is a choice between alternatives: a prompt variant, a model, a
policy. It is not a code change on its own; those go to
[../changelog.md](../changelog.md).

| Date | Roadmap | Decision | Outcome |
|---|---|---|---|
| 2026-09-24 | 1.4b | [Measured, not adopted: translocations annotated for the model (roadmap 1.4b)](2026-09-24-1.4b-translocation-annotation.md) | not adopted |
| 2026-09-24 | 1.9 | [Prompts no longer depend on the hash seed; diagnosis candidates in a fixed shuffle (roadmap 1.9)](2026-09-24-1.9-prompt-order.md) | adopted: sorted gene lists, diagnosis candidates in a SHA-256 shuffle |
| 2026-09-24 | 2.1, 2.2, 2.4 | [Measured: no stage-2 arm beats production (roadmap 2.1, 2.2, 2.4)](2026-09-24-2.1-2.2-2.4-stage-2-arms.md) | not adopted: production stage 2 kept |
| 2026-09-24 | 2.6 | [Measured: Sonnet 5 for stage 2 only is more precise but loses curated diagnoses (roadmap 2.6)](2026-09-24-2.6-sonnet-stage-2.md) | not adopted: loses curated diagnoses |
| 2026-09-24 | D1 | [Backend: Claude Haiku 4.5 through the Anthropic API](2026-09-24-D1-anthropic-haiku-backend.md) | adopted: Claude Haiku 4.5 (claude-haiku-4-5-20251001) through the Anthropic API |
| 2026-09-24 | 3.0, D6 | [Stale review copies are kept and reported (roadmap 3.0, decision D6)](2026-09-24-D6-stale-review-copies.md) | adopted: keep the review copy, publish it, report the conflict |
| 2026-09-24 | - | [Measured: does a larger Claude model map more correctly?](2026-09-24-larger-claude-models.md) | not adopted: Haiku 4.5 stays; neither larger model improves recall |
| 2026-09-27 | 2.8 | [Diagnosis input: labelled sections and an exclusion rule (roadmap 2.8)](2026-09-27-2.8-diagnosis-input.md) | adopted: DIAGNOSIS_INPUT = labelled |
| 2026-09-28 | 2.9 | [Genomic prompt: roles (roadmap 2.9, 2026-09-28)](2026-09-28-2.9-genomic-prompt-roles.md) | adopted: GENOMIC_PROMPT = roles |
| 2026-09-28 | 2.9b | [Measured and rejected: roles_union (roadmap 2.9b, 2026-09-28)](2026-09-28-2.9b-roles-union.md) | rejected |
| 2026-09-28 | 2.9, option A | [Genes kept out of the match tree are published, not queued (2026-09-28)](2026-09-28-option-a-genes-not-required.md) | adopted: published as genes_not_required, not queued |
| 2026-10-01 | -, supersedes D1 | [Backend: gpt-oss:120b on Ollama, for reproducibility (2026-10-01)](2026-10-01-gpt-oss-backend.md) | adopted: gpt-oss:120b on Ollama replaces Haiku 4.5 as the default |
| 2026-10-02 | 3.4 follow-up | [Diagnosis text floor: populations named in the inclusion text (2026-10-02)](2026-10-02-diagnosis-text-floor.md) | adopted: DIAGNOSIS_TEXT_FLOOR = True |
| 2026-10-02 | 3.4 follow-up | [Disease status is no longer published (2026-10-02)](2026-10-02-no-disease-status.md) | adopted: PUBLISH_DISEASE_STATUS = False |
| 2026-10-02 | 3.4 follow-up | [Gene criteria: three encoding rules and a scope check (2026-10-02)](2026-10-02-gene-rules.md) | adopted: always on; scoped genes route to review |
| 2026-10-03 | 3.4 follow-up | [Three small fixes from the audits: contradictions, floor guards, registry ages (2026-10-03)](2026-10-03-audit-2-small-fixes.md) | adopted: always on |

## Recording a new one

Name the file `YYYY-MM-DD-<roadmap step>-<short-name>.md` and start it like
this:

```markdown
# <what was decided> (roadmap <step>, <date>)

- **Date:** YYYY-MM-DD
- **Roadmap:** <step, or ->
- **Outcome:** adopted: <what> | not adopted | rejected

**Question.** What was being chosen, and why it mattered.

**Method.** Trials (which set, how many), replicates, commit, model and
settings (the `run_id` from `runs/` if the pipeline ran), what was held
fixed.

**Result.** The numbers for every arm, with the paired differences and
intervals where there are replicates, and the per-trial losses, not only
the means.

**Decision.** What was chosen, by whom, and what it costs.
```

Then add a row to the table above, a one-line entry in
[../changelog.md](../changelog.md) if code changed, and the step's line in
[../roadmap.md](../roadmap.md).
