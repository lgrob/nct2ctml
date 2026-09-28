# LLM backends

The model platforms `config.py` can select. For running Ollama on a GPU cluster see [cluster_setup.md](cluster_setup.md) and [local_llm_deployment_guide.md](local_llm_deployment_guide.md). Moved from the README on 2026-09-28.

`config.py` selects the backend with `LLM_PLATFORM` and the model with
`LLM_AI_MODEL`; `utils/llm_platforms.py` implements them. The name is matched
case-insensitively.

| `LLM_PLATFORM` | Notes |
|---|---|
| `Anthropic` | **the production backend.** Hosted Claude API through the `anthropic` package, model pinned to `claude-haiku-4-5-20251001`. Reads the key from `ANTHROPIC_API_KEY` (never put a key in `config.py`); `GPU_SERVER_HOSTNAME` is ignored. A prompt's JSON schema is enforced through a forced tool call, at temperature 0 with no thinking. Haiku 4.5 rejects adaptive thinking and the effort parameter, so the platform refuses `ANTHROPIC_THINKING`/`ANTHROPIC_EFFORT` with it before any call. |
| `Ollama` | the GPU backend; served at `GPU_SERVER_HOSTNAME`. Context and output limits come from `OLLAMA_NUM_CTX` and `OLLAMA_NUM_PREDICT`. |
| `SGLang`, `vllm` | self-hosted, OpenAI-style chat endpoint at `GPU_SERVER_HOSTNAME`. |
| `Local_ai` | a stub; raises `NotImplementedError`. |
| `Replay` | answers from a recorded run instead of a model; see [Provenance and replay](provenance.md). |

`LLM_REQUEST_TIMEOUT_SECONDS` bounds every request. To run the mapping on a
Slurm GPU cluster with Ollama under Apptainer, see
[doc/cluster_setup.md](cluster_setup.md) and
`scripts/run_ollama_mapping.sh` (`sbatch scripts/run_ollama_mapping.sh benchmark`
or `... map-all`), which reads the model from `config.py` and refuses to run
unless `LLM_PLATFORM` is `Ollama`.
