# LLM backends

The model platforms `config.py` can select. For running Ollama on a GPU cluster see [cluster_setup.md](cluster_setup.md) and [local_llm_deployment_guide.md](local_llm_deployment_guide.md). Moved from the README on 2026-09-28.

`config.py` selects the backend with `LLM_PLATFORM` and the model with
`LLM_AI_MODEL`; `utils/llm_platforms.py` implements them. The name is matched
case-insensitively.

| `LLM_PLATFORM` | Notes |
|---|---|
| `Anthropic` | **the production backend.** Hosted Claude API through the `anthropic` package, model pinned to `claude-haiku-4-5-20251001`. Reads the key from `ANTHROPIC_API_KEY` (never put a key in `config.py`); `GPU_SERVER_HOSTNAME` is ignored. A prompt's JSON schema is enforced through a forced tool call, at temperature 0 with no thinking. `anthropic` 1.x no longer takes `temperature` as an argument, so it is sent through `extra_body`; Haiku 4.5 still honours it. Haiku 4.5 rejects adaptive thinking and the effort parameter, so the platform refuses `ANTHROPIC_THINKING`/`ANTHROPIC_EFFORT` with it before any call. |
| `Ollama` | the GPU backend; served at `GPU_SERVER_HOSTNAME`. Context and output limits come from `OLLAMA_NUM_CTX` and `OLLAMA_NUM_PREDICT`, reasoning from `OLLAMA_THINK` (off by default; gpt-oss cannot turn it off and needs `low`, `medium` or `high`, plus a larger `OLLAMA_NUM_PREDICT`, because its reasoning tokens count against it). |
| `SGLang`, `vllm` | self-hosted, OpenAI-style chat endpoint at `GPU_SERVER_HOSTNAME`. |
| `Local_ai` | a stub; raises `NotImplementedError`. |
| `Replay` | answers from a recorded run instead of a model; see [Provenance and replay](provenance.md). |

`LLM_REQUEST_TIMEOUT_SECONDS` bounds every request. To run the mapping on a
Slurm GPU cluster with Ollama under Apptainer, see
[doc/cluster_setup.md](cluster_setup.md) and
`scripts/run_ollama_mapping.sh` (`sbatch scripts/run_ollama_mapping.sh benchmark`
or `... map-all`), which reads the model from `config.py` and refuses to run
unless `LLM_PLATFORM` is `Ollama`.

## Switching model or platform

Every setting in `config.py` except the paths can be overridden from the
environment as `NCT2CTML_<NAME>`, for example:

```bash
NCT2CTML_LLM_PLATFORM=Ollama NCT2CTML_LLM_AI_MODEL=llama3.3:70b python main.py map --all
```

`scripts/run_ollama_mapping.sh` reads the model through `config`, so the
same variables apply there. An override does not leave the repository saying
something else without trace. `main.py` logs the overrides at startup, and
each run records them in `runs/<run_id>/run.json`, next to the platform and
model that every mapped file's `_provenance` block names. A bad value (for
example `NCT2CTML_OLLAMA_NUM_CTX=big`) stops at import with the variable
named.

## Models tried

Moved from `config.py` on 2026-09-29 (improvement plan step 10), unchanged.
They are the alternatives and the notes on each: GPU sizes, benchmark
scores, and why each was not adopted. The production model and why it was
chosen are in [decisions/2026-09-24-D1-anthropic-haiku-backend.md](decisions/2026-09-24-D1-anthropic-haiku-backend.md).
Where a note says "uncomment this", set `NCT2CTML_LLM_AI_MODEL` instead.

```python
# deepseek library
# LLM_AI_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
# LLM_AI_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
# LLM_AI_MODEL = "neuralmagic/DeepSeek-R1-Distill-Qwen-32B-quantized.w4a16"

# Anthropic model (used when LLM_PLATFORM = "Anthropic")
# LLM_AI_MODEL = "claude-opus-5"

# --- GPU deployment (LeoMed or any box with >=24 GB VRAM) ------------------
# Start here. Upstream developed every prompt in utils/ai_helper.py against a
# 27B Gemma on Ollama (doc/local_llm_deployment_guide.md), so it is the model
# most likely to work with them unmodified - which means a poor result can be
# read as a model problem rather than a prompt problem. It also has no
# thinking mode, and reasoning tokens are pure cost for structured extraction:
# qwen3:14b once emitted 30,251 of them on a single call and hung for 3.5h.
# ~16 GB at Q4, so it fits a 24 GB card with room for real context.
# Raise OLLAMA_NUM_CTX to 32768 and drop the timeout to ~300 when using this.
# LLM_AI_MODEL = "gemma3:27b"
#
# What is actually running on LeoMed. Benchmarked 2026-09-14 against the
# curated key: gemma3:27b scored dx F1 0.18 / gene F1 0.09, llama3.3:70b
# scored 0.40 / 0.61 on the same twelve trials, so capacity was a real
# constraint rather than a prompting one. ~42 GB at Q4, resident in VRAM on
# an A100-SXM4-80GB with room for the 32k context; ~149 s per trial.
# This line is the single source of truth - scripts/run_ollama_mapping.sh
# reads the model from here, so an uncommitted edit on the cluster means the
# repo no longer says what is running.
# The GPU backend: set LLM_PLATFORM = "Ollama" above and uncomment this.
# LLM_AI_MODEL = "llama3.3:70b"
#
# The same weights are also reachable through Ollama's HuggingFace
# passthrough, which is the form upstream's guide uses. Prefer the tag above:
# it comes from Ollama's own registry, so it needs only registry.ollama.ai
# rather than huggingface.co as well - one less host for a locked-down
# network to refuse.
# LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"
#
# Runner-up for 40 GB+. Likely sharper, but thinking MUST be disabled or it
# reproduces the hang above on better hardware.
# LLM_AI_MODEL = "qwen3:32b"

# Laptop fallback. 14B at Q4 is about 9 GB and fits 16 GB of unified memory.
# Only for exercising the plumbing: it produced 46 oncotree diagnoses where
# the curated answer was 4, with no overlap. Not a production model.
# LLM_AI_MODEL = "qwen3:14b"

# gemma library
# LLM_AI_MODEL = "hf.co/unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL"
# LLM_AI_MODEL = "cyankiwi/gemma-4-31B-it-AWQ-4bit"
# LLM_AI_MODEL = "gemma4:31b" # from official ollama library instead of hugging face
# LLM_AI_MODEL = "gemma4:26b" # from official ollama library instead of hugging face
# LLM_AI_MODEL = "hf.co/unsloth/medgemma-27b-text-it-GGUF:Q4_K_M"
# LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"
# LLM_AI_MODEL = "hf.co/bartowski/gemma-2-27b-it-GGUF:Q4_K_M"

# Qwen library
# LLM_AI_MODEL = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
# LLM_AI_MODEL = "Qwen/Qwen3.6-27B-FP8"
# LLM_AI_MODEL = "qwen3.6:27b" # from official ollama library instead of hugging face
# LLM_AI_MODEL = "qwen3.6:35b" # from official ollama library instead of hugging face

# GLM library
# LLM_AI_MODEL = "hf.co/mradermacher/GLM-4-32B-0414-GGUF:Q4_K_M"
# LLM_AI_MODEL = "hf.co/lmstudio-community/GLM-Z1-32B-0414-GGUF:Q4_K_M"

# moonshotai library
# LLM_AI_MODEL = "moonshotai/Moonlight-16B-A3B-Instruct"
# LLM_AI_MODEL = "hf.co/mmnga/Moonlight-16B-A3B-Instruct-gguf:Q8_0"

# minimax library
# LLM_AI_MODEL = "hf.co/mradermacher/SynLogic-32B-GGUF:Q4_K_M"
```
