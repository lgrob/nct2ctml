# Local LLM Deployment Guide

> Upstream's guide for its own GPU server at HKU, kept as upstream wrote it.
> For this fork: the production backend is the Anthropic API
> ([llm_backends.md](llm_backends.md)), and a GPU cluster run is described
> in [cluster_setup.md](cluster_setup.md). Where this guide says to set a
> variable in `config.py`, `NCT2CTML_<NAME>` in the environment does the same.

This document collects commands for running several local LLMs on GPU02 (gpu02.sbms.hku.hk).

## 1. `sglang` server (Qwen 3.5 35B, GPTQ Int4)

- Client-side settings:
- In `config.py`, set following variables:
  - `LLM_PLATFORM = "SGLang"`
  - `LLM_AI_MODEL = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"` (or local path)
  - API endpoint port is defined in `utils/llm_platforms.py` (default 30000 for SGLang).

- Server side settings:
- Conda environment: `sglang-env` 

```bash
conda activate sglang-env
CUDA_VISIBLE_DEVICES=0,1 python -m sglang.launch_server \
  --model-path Qwen/Qwen3.5-35B-A3B-GPTQ-Int4 \
  --port 30000 \
  --tp-size 2 \
  --mem-fraction-static 0.8 \
  --context-length 262144 \
  --reasoning-parser qwen3
```

## 2. Ollama service (Gemma 3 27B, GGUF Q4_K_M)

- Client-side settings:
- In `config.py`, set following variables:
  - `LLM_PLATFORM = "Ollama"`
  - `LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"`
  - API endpoint port is defined in `utils/llm_platforms.py` (default 11434 for Ollama).

- Server side settings:
- Note: `ollama service` is already running on `gpu02.sbms.hku.hk`, so there is no need to run `ollama run {model}` manually.
- Ollama does not auto-pull models. If the requested model is not already downloaded locally, API requests will fail with a 404 `model not found` error.
- Step 1: pull the model first so it is available in the local cache:

```bash
ollama pull hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M
```

- Step 2: send the API request directly once the model is pulled:

```bash
curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model": "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M", "messages": [{"role": "user", "content": "Hello"}], "stream": false}'
```

- Check downloaded models with:
  - `curl http://gpu02.sbms.hku.hk:11434/api/tags`

- After sending request for a specific `LLM_AI_MODEL`, check if it was loaded:
  - `ollama ps`

## 3. `sglang` server (DeepSeek R1 (quantized))

- Client-side settings:
- In `config.py`, set following variables:
  - `LLM_PLATFORM = "SGLang"`
  - `LLM_AI_MODEL = "neuralmagic/DeepSeek-R1-Distill-Qwen-32B-quantized.w4a16"`
  - API endpoint port is defined in `utils/llm_platforms.py` (default 30000 for SGLang).

- Server side settings:
Option A: Direct command (assumes correct `conda` env is already active, or run this from within `vllm` env):

```bash
CUDA_VISIBLE_DEVICES=${GPU_DEVICE:-2} python3 -m sglang.launch_server \
  --model neuralmagic/DeepSeek-R1-Distill-Qwen-32B-quantized.w4a16 \
  --context-length 131072 \
  --trust-remote-code \
  --host 0.0.0.0
```

Option B: Run helper script (activates the correct env inside):

```bash
./run_deepseek_sglang.sh
```

> Tip: `run_deepseek_sglang.sh` needs `CUDA_VISIBLE_DEVICES` set. If not set, the script defaults to GPU 2.
> 
> Ensure it is set explicitly when required, e.g. `export CUDA_VISIBLE_DEVICES=0`.
