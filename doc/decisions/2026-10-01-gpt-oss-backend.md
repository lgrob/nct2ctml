# Backend: gpt-oss:120b on Ollama, for reproducibility (2026-10-01)

- **Date:** 2026-10-01
- **Roadmap:** -, supersedes [D1](2026-09-24-D1-anthropic-haiku-backend.md)
- **Outcome:** adopted: gpt-oss:120b on Ollama (`think: low`,
  `num_predict` 16384) replaces Claude Haiku 4.5 as the default backend

**Question.** Should the default mapping model be one whose weights the
project can keep? Haiku 4.5 is reached as a hosted snapshot
(`claude-haiku-4-5-20251001`). Once Anthropic retires it, no mapping it made
can be rerun, only replayed from saved answers. A model run on the project's
own cluster can be archived with its weights and rerun as long as they are
kept. The choice was the user's, for that reason, after the measurements
below showed the local models at Haiku's level.

**Method.** The 56 curated benchmark trials (50 NCT, 6 CTIS), scored against
`ctml/reviewed` by `bench/benchmark_map.py`.
- **gpt-oss:120b:** Ollama 0.34.0 on one A100-SXM4-80GB, temperature 0,
  seed 42, `top_k` 1, `think: low`, `num_predict` 16384. Run
  `20260930T200508Z-6e452d` (job 6758304), rescored at 412f46c from its saved
  answers.
- **qwen3.6:27b:** the same, with thinking off and `num_predict` 8192. Run
  `20260930T164949Z-12380b`, rescored at 412f46c.
- **Haiku 4.5:** run at bbcc526 and at 412f46c, numbers as reported by the
  user.
- One run per model. Ollama at temperature 0 with a fixed seed and `top_k` 1
  is close to deterministic, so no replicate was run; Haiku at temperature 0
  differed between two runs on 6 of 50 trials
  ([larger-claude-models](2026-09-24-larger-claude-models.md)). Details of the
  local runs, including the defects found on the way, are in
  [../runs/2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md](../runs/2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md).

**Result.** NCT, 50 trials:

|  | Haiku 4.5 bbcc526 | Haiku 4.5 412f46c | qwen3.6:27b 412f46c | gpt-oss:120b 412f46c |
|---|---|---|---|---|
| diagnosis population recall | 0.948 | 0.948 | 0.93 | 0.94 |
| diagnosis population precision | 0.793 | 0.793 | 0.81 | 0.76 |
| diagnosis name F1 | 0.745 | 0.745 | 0.76 | 0.75 |
| gene F1 | 0.647 | 0.684 | 0.75 | 0.78 |
| age F1 | 0.899 | 0.899 | 0.92 | 0.91 |
| routed to review (of 56) | 9 | 15 | 12 | 10 |

CTIS, 6 trials, at 412f46c: gpt-oss population recall 0.79, name F1 0.74,
gene F1 0.83; qwen 0.64, 0.66, 0.67. Haiku's CTIS numbers at 412f46c were not
recorded here; its full run of 2026-09-25 had population recall 0.836 on 5.

- **Diagnoses:** no model is better. Recall differs by under 0.01 (less than
  one trial of 50), and gpt-oss is the least precise (0.76 against 0.79).
- **Genes:** both local models score above Haiku (0.78 and 0.75 against
  0.68). This is the largest difference, but it was not paired per trial, and
  on 50 trials it can rest on five or six of them.
- **qwen3.6:27b is not adopted:** level with gpt-oss on NCT, clearly behind
  on CTIS.

**What was not measured.** No per-trial paired comparison with intervals, as
CONTRIBUTING asks for a change of default. Haiku's CTIS recall was not compared
on the same commit, and CTIS is where gpt-oss looked weakest (0.79 against
0.84 earlier, on six trials). This decision rests on reproducibility, not on
a measured improvement.

**Decision.** Taken by the user. `config.py` defaults to `LLM_PLATFORM =
"Ollama"`, `LLM_AI_MODEL = "gpt-oss:120b"`, `OLLAMA_THINK = "low"`,
`OLLAMA_NUM_PREDICT = 16384`.
- **Reproducibility needs the weights, not the tag.** `gpt-oss:120b` names
  whatever the registry holds under it. Every run now records the digest of
  the weights it was served (`run.json` and each file's `_provenance`), and
  `OLLAMA_MODEL_DIGEST` pins one: a run then refuses to start on other
  weights. The pin is left unset until the digest of the benchmarked weights
  is copied from the cluster (`ollama list` / `/api/tags`). The weights
  (about 65 GB) are kept under the project's Ollama model directory.
- **Costs:** the API bill goes, and GPU time comes instead: 51 minutes for 56
  trials on one A100, so roughly 18 hours for the 1,171-trial corpus.
- **Not covered:** the current CTML in `cache/ctml`, `ctml/needs-review` and
  the index were mapped with Haiku and stay so until the corpus is remapped.
  The Anthropic backend stays available for comparison runs
  (`NCT2CTML_LLM_PLATFORM=Anthropic
  NCT2CTML_LLM_AI_MODEL=claude-haiku-4-5-20251001`).
