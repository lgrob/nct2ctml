# Benchmark: qwen3.6:27b and gpt-oss:120b on Ollama (2026-09-30)

The first measurement of self-hosted models on the current pipeline since
llama3.3:70b (2026-09-14). One replicate per model, so it shows whether either
is worth a proper comparison with Haiku 4.5; it does not settle one.

## Inputs
- **Platform:** Ollama 0.34.0 under Apptainer/Singularity on the UZH Slurm
  cluster, `scripts/run_ollama_mapping.sh benchmark`. Temperature 0, seed 42,
  `top_k` 1, `num_ctx` 32768, JSON schema through `format`. Ollama library
  builds of both models.
- **Trials:** the 56 curated benchmark trials (50 NCT, 6 CTIS), registry
  cache as on the cluster.
- **qwen3.6:27b:** job 6752539, one H100 NVL (18.4 GB in VRAM), thinking off,
  `num_predict` 8192. The job ran before a9aae13, whose two defects (below)
  made its own report unusable. Its saved answers (run `20260930T164949Z-12380b`)
  were therefore replayed (`LLM_PLATFORM=Replay`) at a9aae13 into `bench/output-qwen3.6-27b-replay/`:
  replay run `20260930T193526Z-6cb7f8`, 56 of 56 trials, no replay misses.
  Every model answer is from the job, and the code around it is a9aae13's.
- **gpt-oss:120b:** job 6758304 at a9aae13, one A100-SXM4-80GB (64.5 GB in
  VRAM), `OLLAMA_THINK=low`, `num_predict` 16384, run
  `20260930T200508Z-6e452d`, into `bench/output-gpt-oss-120b/`. 51 minutes
  for the 56 trials. No call came back empty or cut off at the length limit.
- The `runs/` directories stay on the cluster checkout; they are the only
  copy of the answers.

## Result

|  | Haiku 4.5, full run 2026-09-25 | Haiku 4.5, 2 replicates 2026-09-24 | qwen3.6:27b | gpt-oss:120b |
|---|---|---|---|---|
| NCT trials scored | 50 | 50 | 50 | 50 |
| diagnosis population recall | 0.951 | 0.935 | 0.93 | 0.94 |
| diagnosis population precision | 0.795 | 0.781 | 0.81 | 0.76 |
| diagnosis name F1 | 0.728 | 0.723 | 0.76 | 0.75 |
| gene F1 | 0.593 | 0.639 | 0.75 | 0.76 |
| age F1 | 0.899 | 0.908 | 0.92 | 0.91 |
| CTIS population recall | 0.836 (5 trials) | - | 0.64 (6) | 0.79 (6) |
| CTIS name F1 | 0.804 (5) | - | 0.66 (6) | 0.74 (6) |
| CTIS gene F1 | 0.978 (5) | - | 0.67 (6) | 0.83 (6) |
| routed to review | - | - | 7 of 56 | 5 of 56 |

The Haiku columns are from
[2026-09-25-3.2-full-run.md](2026-09-25-3.2-full-run.md) and
[../decisions/2026-09-24-larger-claude-models.md](../decisions/2026-09-24-larger-claude-models.md),
on older code and, for CTIS, one trial fewer. The comparison is indicative
only, not paired.

- **NCT diagnoses:** both models are at Haiku's level. Every difference is
  within the spread of Haiku's own replicates (it differed between two runs at
  temperature 0 on 6 of 50 trials).
- **Genes:** both means are above Haiku's (0.75-0.76 against 0.59-0.64).
  Seven trials score 0.00 for both models: NCT03838042, NCT04221035,
  NCT05748171, NCT06239272, NCT06528691, NCT07059975, NCT07440290. A failure
  shared this exactly by two different models points at the key, the gene
  filter or the scoring rather than at either model. Not yet read
  (`genes_got` / `genes_truth` in the reports).
- **Over-generation shared by both models:** NCT04732065 and NCT06528691 got
  exactly 126 diagnoses from each (4 and 1 curated), and NCT04897321 73 and
  78 (12 curated). The trials' own condition lists seed only 1-9 diagnoses
  (`bench/baseline_conditions_nct.json`), so this is not the conditions seed.
  The identical count of 126 suggests one broad CNS node expanded to its
  subtree. Not yet checked.
- **Differences between the two:** Qwen also over-generated on NCT04775485
  (121, against 6 from gpt-oss). gpt-oss over-generated mildly on
  NCT02443831, NCT04696029 and NCT05366218 (4-8 against 1).
- **CTIS:** gpt-oss is near Haiku (population recall 0.79 against 0.84);
  Qwen is clearly worse (0.64). Six trials only.
- **Review routing:** Qwen NCT02332668, NCT03067181, NCT04732065,
  NCT05009992, NCT05580562, NCT06239272, NCT07215910. gpt-oss NCT03067181,
  NCT04775485, NCT05009992, NCT05580562, 2023-504694-20-00.

## Rescored at 412f46c (2026-10-01)

Both runs were replayed again from the same saved answers (runs
`20260930T164949Z-12380b` and `20260930T200508Z-6e452d`) at 412f46c, into
`bench/output-qwen3.6-27b-v2/` and `bench/output-gpt-oss-120b-v2/`. No model
was called. 412f46c adds three things: `genomic_emptied`, the
`variant_category` guard and the gene-anchored cohort cue (changelog
"A genomic answer dropped to nothing goes to review"), and
`diagnosis_over_generated` (changelog "A diagnosis call that answers with its
candidate list goes to review").

| NCT (50 trials) | qwen3.6:27b a9aae13 | qwen3.6:27b 412f46c | gpt-oss:120b a9aae13 | gpt-oss:120b 412f46c |
|---|---|---|---|---|
| diagnosis population recall | 0.93 | 0.93 | 0.94 | 0.94 |
| diagnosis population precision | 0.81 | 0.81 | 0.76 | 0.76 |
| diagnosis name F1 | 0.76 | 0.76 | 0.75 | 0.75 |
| gene F1 | 0.75 | 0.75 | 0.76 | 0.78 |
| age F1 | 0.92 | 0.92 | 0.91 | 0.91 |
| routed to review (of 56) | 7 | 12 | 5 | 10 |

CTIS is unchanged for both models.

- **Genes:** gpt-oss gains on two trials, NCT05580562 (0.00 to 0.86, the
  trial the cue fix names) and NCT05745714 (0.87 to 0.96). Qwen already
  scored 0.86 on NCT05580562 and does not move. The zero-gene trials still
  score 0.00: the new rule sends an emptied trial to review rather than
  recovering its genes, and the benchmark does not score that.
- **Newly routed, both models:** NCT02443831, NCT04897321, NCT06528691.
  Qwen only: NCT04775485, 2023-509392-17-00. gpt-oss only: NCT04732065
  (already routed for Qwen at a9aae13), NCT05489887.
- **Reasons, read for gpt-oss:** NCT02443831 `genomic_emptied: CD19; CD22`
  (plus `gene_role_dropped` for KMT2A, TCF3, BCR as risk groups);
  NCT05489887 `genomic_emptied: MYCN`; NCT04897321, NCT04732065 and
  NCT06528691 by `diagnosis_over_generated`, the three trials with 78-126
  diagnoses.
- **`genomic_emptied` fires where the drop is the intended result.** On
  NCT02443831 both symbols are antigens, which `filter_genomic_criteria`
  removes on purpose (flow or IHC, not sequencing), so the trial correctly
  has no genomic criterion and is still sent to review. The same will hold
  for other antigen-targeted trials. NCT05489887 (MYCN) may be the same
  pattern through the cohort drop; not checked. Recorded here, not changed.

## Defects found
1. **The benchmark dropped review-routed trials from the score.** They were
   written to `ctml/needs-review` and scored as MISSING OUTPUT: 7 of 56 in
   the qwen job, which raised the means (its own NCT name F1 read 0.81 on 43
   trials, against 0.76 on all 50). Fixed in a9aae13.
2. **Concurrent jobs shared one output directory.** The old script wrote
   every model to `bench/output/` and `bench/report.json`. A gpt-oss job
   started while the qwen one ran, so the `bench/report.json` committed in
   1ce15b4 mixed the two runs and was not a result for either; bbcc526
   restored the file it replaced. Fixed in a9aae13
   (`bench/output-<model>[-rep<N>]/`).
3. **The first gpt-oss:120b run answered nothing.** The old code sent it
   `think: false`, which gpt-oss ignores. All 324 recorded calls (run
   `20260930T185930Z-983d21`) ended normally (`done_reason: stop`, ~81 tokens
   generated) with empty content and no thinking field. The reasoning was
   discarded and no answer followed. The job was cancelled. A single call
   with `think: "low"` and a `format` schema then returned the reasoning and
   valid JSON, and the rerun above used that. a9aae13 adds `OLLAMA_THINK`,
   and the script refuses gpt-oss with thinking off.

## Not done
- **Replicates of the local models** were not run: at temperature 0 with a
  fixed seed and `top_k` 1 they are close to deterministic, so the
  uncertainty that matters is the 50-trial sample, handled by pairing per
  trial.
- **The shared failures** were read on 2026-10-01; the findings and fixes
  are in the changelog entries named above. The zero-gene trials that are
  not explained there have not been read.
- **Haiku on the same commit**, to pair the comparison per trial.
