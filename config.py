# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.


#GPU_SERVER_HOSTNAME = "http://gpu02.sbms.hku.hk"
#GPU_SERVER_HOSTNAME = "http://127.0.0.1"
GPU_SERVER_HOSTNAME = "http://localhost"

# Options: Local_ai, vllm, SGLang, Ollama, Anthropic
#LLM_PLATFORM = "Anthropic"
LLM_PLATFORM = "Ollama"

# Anthropic (hosted Claude API) settings.
# Auth comes from the ANTHROPIC_API_KEY environment variable - do not put a key here.
# Only used when LLM_PLATFORM = "Anthropic"; GPU_SERVER_HOSTNAME is ignored in that case.
ANTHROPIC_EFFORT = "high"      # low | medium | high | xhigh | max
ANTHROPIC_MAX_TOKENS = 16000

# deepseek library
#LLM_AI_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
#LLM_AI_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
#LLM_AI_MODEL = "neuralmagic/DeepSeek-R1-Distill-Qwen-32B-quantized.w4a16"

# Anthropic model (used when LLM_PLATFORM = "Anthropic")
#LLM_AI_MODEL = "claude-opus-5"

# --- GPU deployment (LeoMed or any box with >=24 GB VRAM) ------------------
# Start here. Upstream developed every prompt in utils/ai_helper.py against a
# 27B Gemma on Ollama (doc/local_llm_deployment_guide.md), so it is the model
# most likely to work with them unmodified - which means a poor result can be
# read as a model problem rather than a prompt problem. It also has no
# thinking mode, and reasoning tokens are pure cost for structured extraction:
# qwen3:14b once emitted 30,251 of them on a single call and hung for 3.5h.
# ~16 GB at Q4, so it fits a 24 GB card with room for real context.
# Raise OLLAMA_NUM_CTX to 32768 and drop the timeout to ~300 when using this.
#LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"
#
# Runner-up for 40 GB+. Likely sharper, but thinking MUST be disabled or it
# reproduces the hang above on better hardware.
#LLM_AI_MODEL = "qwen3:32b"

# Local model via Ollama (free, runs on this machine, no data leaves it).
# 14B at Q4 is about 9 GB and fits 16 GB of unified memory; the 32B models
# commented out above do not. Benchmarked at dx F1 far below curation grade -
# see bench/ - so this is a plumbing model, not a production one.
LLM_AI_MODEL = "qwen3:14b"

# gemma library
#LLM_AI_MODEL = "hf.co/unsloth/gemma-4-31B-it-GGUF:UD-Q4_K_XL"
#LLM_AI_MODEL = "cyankiwi/gemma-4-31B-it-AWQ-4bit"
#LLM_AI_MODEL = "gemma4:31b" # from official ollama library instead of hugging face
#LLM_AI_MODEL = "gemma4:26b" # from official ollama library instead of hugging face
#LLM_AI_MODEL = "hf.co/unsloth/medgemma-27b-text-it-GGUF:Q4_K_M"
#LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"
#LLM_AI_MODEL = "hf.co/bartowski/gemma-2-27b-it-GGUF:Q4_K_M"

# Qwen library
#LLM_AI_MODEL = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
#LLM_AI_MODEL = "Qwen/Qwen3.6-27B-FP8"
#LLM_AI_MODEL = "qwen3.6:27b" # from official ollama library instead of hugging face
#LLM_AI_MODEL = "qwen3.6:35b" # from official ollama library instead of hugging face

# GLM library
#LLM_AI_MODEL = "hf.co/mradermacher/GLM-4-32B-0414-GGUF:Q4_K_M"
#LLM_AI_MODEL = "hf.co/lmstudio-community/GLM-Z1-32B-0414-GGUF:Q4_K_M"

# moonshotai library
#LLM_AI_MODEL = "moonshotai/Moonlight-16B-A3B-Instruct"
#LLM_AI_MODEL = "hf.co/mmnga/Moonlight-16B-A3B-Instruct-gguf:Q8_0"

# minimax library
#LLM_AI_MODEL = "hf.co/mradermacher/SynLogic-32B-GGUF:Q4_K_M"



ONCOTREE_TXT_FILE_PATH = "ref/oncotree_file.txt"
GENE_LIST_FILE_PATH = "ref/genes.txt"

# Mapping configuration
# Number of days back to consider for mapping trials
# Trials with entry_last_updated_date within this many days will be mapped
MAPPING_CUTOFF_DAYS = 1
# Guard rails for self-hosted models.
# LLM_REQUEST_TIMEOUT_SECONDS bounds every LLM HTTP call; without it a runaway
# generation loop blocks the pipeline indefinitely.
# 2048 tokens at the ~2.4 tok/s a 14B manages on a 16 GB M3 needs ~850s, so the
# timeout must exceed that or it fires before num_predict can cap a runaway.
LLM_REQUEST_TIMEOUT_SECONDS = 1200
# Ollama defaults num_ctx to 4096, too small for the genomic prompts.
# Prompts peak around 12k chars (~3k tokens), so 8192 is ample; 16384 only adds
# KV cache pressure on a machine already swapping under the 9.3 GB model.
# On a GPU this constraint disappears: raise to 32768. The longest criteria
# text in the corpus is 19,676 chars (~4,900 tokens) before the prompt
# wrapper, gene list and oncotree terms are added, and Ollama truncates an
# over-long prompt silently rather than erroring.
OLLAMA_NUM_CTX = 8192
OLLAMA_NUM_PREDICT = 2048
