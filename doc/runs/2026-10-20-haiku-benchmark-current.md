# Benchmark: Claude Haiku 4.5 on the live API at the current pipeline (2026-10-20)

- **Date:** 2026-10-20
- **Roadmap:** D1 evidence; follows 0.4
- **Backend:** `claude-haiku-4-5-20251001` through the Anthropic API,
  `anthropic` 1.4.0, temperature 0, no thinking, forced-tool JSON. Not the
  default backend, which is gpt-oss:120b on Ollama.

## Summary

The first Haiku benchmark on the live API, and the first Haiku measurement
of the pipeline since 412f46c, which predates the text floor, the gene rules
and the arm check. All 60 curated trials were mapped and scored: 50 NCT and
10 CTIS. That is 821 calls with no API errors, for $2.98, or $0.050 a trial.
Against Haiku's own replayed answers at 412f46c, on the same 50 NCT trials:

- **Population recall rises from 0.948 to 0.979.** It falls on no trial and
  rises on five.
- **Precision falls from 0.793 to 0.679.** The mean number of diagnoses rises
  from 7.0 to 10.3.
- **Gene F1 rises from 0.684 to 0.739.**

That is the same trade the text floor made on gpt-oss: recall kept or
gained, precision given up, because the floor only adds diagnoses.

## Inputs

- **Commit:** the cluster checkout at `af2dbac` or later (`run.json`
  records the exact commit).
- **Run:** `runs/20261020T114143Z-04720d`, through
  `scripts/run_anthropic_mapping.sh benchmark`. Output is in
  `bench/output-claude-haiku-4-5-20251001/`, and the report was copied to the
  Mac checkout.
- **Trials:** every file in `ctml/reviewed` at the time: 50 NCT and 10 CTIS.
  CTIS is 5 trials more than at 412f46c, because the key gained
  2022-500783-35-00, 2022-501866-22-00, 2022-502051-56-00 and
  2022-502503-30-00 (65b4dc5). 2024-511989-36-00 is in the key and in the
  cluster's registry cache, but not in the Mac's.
- **Comparison:** the Haiku replay at 412f46c of 2026-10-01 (artifact
  `haiku_412f46c_report.json`). That replay was part recorded answers and
  part new calls through the analysis environment, at temperature 0.
- **The key is comparable.** The only change to the 50 NCT key files since
  412f46c is the removal of `disease_status` from 20 of them (316c2fe), and
  the scorer does not read it. The NCT deltas below are pipeline and model,
  not key.

## Result

| NCT, 50 trials | Haiku at 412f46c (replay) | Haiku now (live API) | change |
|---|---|---|---|
| population recall | 0.948 | **0.979** | +0.031 |
| population precision | 0.793 | 0.679 | -0.114 |
| diagnosis name recall | 0.935 | 0.966 | +0.031 |
| diagnosis name precision | 0.695 | 0.545 | -0.150 |
| diagnosis name F1 | 0.745 | 0.629 | -0.116 |
| gene F1 | 0.684 | **0.739** | +0.055 |
| age F1 | 0.899 | 0.906 | +0.007 |
| mean diagnoses per trial | 7.0 | 10.3 | |
| routed to review | 12 | 20 | +8, none back to mapped |
| exactly right by population | 33 | 23 | -10 |

CTIS on the 5 trials both runs share: recall 0.836 in both, precision 1.000
to 0.848, gene F1 0.978 in both. The 5 CTIS trials new to the key score
recall 1.000, precision 0.811 and gene F1 0.971.

**Cost:** 2,188,726 input and 158,229 output tokens, 13.7 calls a trial.
At the $1/$5 list price that is $2.98, or $0.050 a trial, which is more
than the smoke test's $0.040 on three short trials. The 1,137 in-scope
trials would cost about **$56 at list price and $28 through the Batch API**.

### What moved

- **Recall: 5 trials up, 0 down.** NCT04775485 0.50 → 1.00, NCT05180825
  0.40 → 1.00, NCT03067181 0.71 → 1.00, NCT02332668 0.75 → 0.86,
  NCT06239272 0.96 → 1.00. The lowest recall on any trial is now 0.50, and
  no trial has 0.
- **Precision: 27 trials gained diagnoses, 2 lost some, 21 are unchanged.**
  The biggest additions are on already broad trials: NCT04897321 51 → 70,
  NCT04185038 55 → 72, NCT03838042 14 → 29, NCT04732065 31 → 45 and
  NCT07110246 1 → 14. This is the text floor's known cost. On gpt-oss it
  took precision from 0.810 to 0.681
  ([../decisions/2026-10-02-diagnosis-text-floor.md](../decisions/2026-10-02-diagnosis-text-floor.md)),
  the same size of drop as here.
- **Genes: 4 trials up, 1 down.**
  - NCT03838042 0.00 → 1.00 (MYC, MYCN): the 2026-10-01 zero-gene trial
    whose key writes MYC(N).
  - NCT07297979 0.50 → 1.00 (ERG, EWSR1, FLI1).
  - NCT05183035 0.67 → 1.00 (FLT3).
  - NCT02443831 0.00 → 1.00: the key has no gene. The replay at 412f46c
    returned TCF3, and this run returns none.
  - NCT05745714 0.96 → 0.87: this run lost DDX3X and P2RY8 and still adds
    BCL2. Probably run-to-run variation; one run cannot tell.
- **Routing: 8 NCT trials newly routed, none back to mapped.** NCT02443831,
  NCT04094610, NCT04655404, NCT05183035, NCT05366218, NCT05918640,
  NCT06528691 and NCT07012447. Only the report was copied, not the CTML, so
  the flags behind each are not read here. The arm-narrower check (010f877)
  and the floor's exclusion check are the likely sources.

## Against gpt-oss:120b (D1)

| NCT, 50 trials | gpt-oss:120b, replay after 8ed3a9e | Haiku 4.5 now |
|---|---|---|
| population recall | 0.96 | 0.979 |
| population precision | 0.65 | 0.679 |

The gpt-oss figures are from
[../decisions/2026-10-03-floor-groups-and-title.md](../decisions/2026-10-03-floor-groups-and-title.md),
reported to two decimals. They are a replay of the recorded gpt-oss answers
through the pipeline after the floor groups (8ed3a9e). The Haiku run also
has 905fd0d's floor rows and the arm check.

**This is not yet a paired comparison**, for three reasons:

1. No per-trial gpt-oss report at the current commit is on the Mac.
2. Gene and age F1 for gpt-oss have not been reported since the gene rules
   (844e3da). The last figure, 0.78 at 412f46c, predates them.
3. Neither model has a replicate at this commit.

On what is there, Haiku is level with or slightly ahead of gpt-oss on
diagnoses. That is the reverse of the 2026-09-30 reading, which had both
models at Haiku's level before the floor.

## Not done

- **A paired gpt-oss column.** One command on the cluster gives it, from
  the recorded answers with no GPU:
  `NCT2CTML_LLM_PLATFORM=Replay NCT2CTML_REPLAY_FILE=runs/20260930T200508Z-6e452d/llm_calls.jsonl ./.venv/bin/python -m bench.benchmark_map --out bench/output-gpt-oss-120b-v3 --json bench/output-gpt-oss-120b-v3/report.json`.
  Prompts that changed since that run will miss, and the benchmark scores
  the affected trials as failed. A fresh gpt-oss benchmark run avoids that.
- **A Haiku replicate** at this commit, to put an interval on the deltas
  above. Another ~$3.
- **The flags behind the 8 newly routed trials.** That needs the CTML under
  `bench/output-claude-haiku-4-5-20251001/needs-review/`.
