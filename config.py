# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.


#GPU_SERVER_HOSTNAME = "http://gpu02.sbms.hku.hk"
#GPU_SERVER_HOSTNAME = "http://127.0.0.1"
# 127.0.0.1 rather than localhost or 0.0.0.0: proxied sites list
# 127.0.0.1 in NO_PROXY, and a client aimed at 0.0.0.0 gets routed to the
# proxy, which cannot reach a port on the compute node.
GPU_SERVER_HOSTNAME = "http://127.0.0.1"

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
#LLM_AI_MODEL = "gemma3:27b"
#
# What is actually running on LeoMed. Benchmarked 2026-09-14 against the
# curated key: gemma3:27b scored dx F1 0.18 / gene F1 0.09, llama3.3:70b
# scored 0.40 / 0.61 on the same twelve trials, so capacity was a real
# constraint rather than a prompting one. ~42 GB at Q4, resident in VRAM on
# an A100-SXM4-80GB with room for the 32k context; ~149 s per trial.
# This line is the single source of truth - scripts/run_ollama_mapping.sh
# reads the model from here, so an uncommitted edit on the cluster means the
# repo no longer says what is running.
LLM_AI_MODEL = "llama3.3:70b"
#
# The same weights are also reachable through Ollama's HuggingFace
# passthrough, which is the form upstream's guide uses. Prefer the tag above:
# it comes from Ollama's own registry, so it needs only registry.ollama.ai
# rather than huggingface.co as well - one less host for a locked-down
# network to refuse.
#LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"
#
# Runner-up for 40 GB+. Likely sharper, but thinking MUST be disabled or it
# reproduces the hang above on better hardware.
#LLM_AI_MODEL = "qwen3:32b"

# Laptop fallback. 14B at Q4 is about 9 GB and fits 16 GB of unified memory.
# Only for exercising the plumbing: it produced 46 oncotree diagnoses where
# the curated answer was 4, with no overlap. Not a production model.
#LLM_AI_MODEL = "qwen3:14b"

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



# Where a mapped trial goes when it needs a human before it is usable -
# currently, when no Oncotree diagnosis could be determined at all. Kept out of
# the normal output so nobody loads it into MatchMiner by accident, and kept as
# a directory rather than a log line so the queue is visible without grepping.
#
# Not ctml/pending: the README gives that directory to hand-authored CTML for
# local trials awaiting review. Both are review queues, so nothing reaches
# MatchMiner unreviewed either way, but sharing one directory means a reviewer
# opening it cannot tell a colleague's draft from machine output that failed to
# find a diagnosis. Those need opposite kinds of attention.
CTML_REVIEW_PATH = "ctml/needs-review"

ONCOTREE_TXT_FILE_PATH = "ref/oncotree_file.txt"
# The gene reference, in the three roles it actually plays.
# GENE_LIST_FILE_PATH is the accept-list: what a hugo_symbol is allowed
# to be in the output. The two synonym tables are the input side: what
# spellings of a gene are recognised in a trial's criteria text.
# LEGACY_GENE_LIST_FILE_PATH is provenance - the raw list as Kispi
# supplied it - and its only runtime use is that the difference from
# GENE_LIST_FILE_PATH defines which retired spellings may be rewritten.
GENE_LIST_FILE_PATH = "ref/genes.txt"
LEGACY_GENE_LIST_FILE_PATH = "ref/genes_kispi.txt"
GENE_SYNONYM_FILE_PATH = "ref/synonym_to_gene_symbol.tsv"
GENE_SYNONYM_ADDENDUM_FILE_PATH = "ref/gene_synonym_addendum.tsv"
# Registry disease spellings that folding cannot reach - lineage decisions,
# WHO reclassifications and registry house style. See the header of the file
# itself for what belongs in it and what does not.
DIAGNOSIS_SYNONYM_FILE_PATH = "ref/diagnosis_synonyms.tsv"

# Mapping configuration
# Number of days back to consider for mapping trials
# Trials with entry_last_updated_date within this many days will be mapped
MAPPING_CUTOFF_DAYS = 1
# Guard rails for self-hosted models.
# LLM_REQUEST_TIMEOUT_SECONDS bounds every LLM HTTP call; without it a runaway
# generation loop blocks the pipeline indefinitely.
# 2048 tokens at the ~2.4 tok/s a 14B manages on a 16 GB M3 needs ~850s, so the
# timeout must exceed that or it fires before num_predict can cap a runaway.
# Must exceed the time OLLAMA_NUM_PREDICT tokens take to generate, or it
# fires before the cap can do its job. 8192 tokens at ~30-40 tok/s is
# ~205-273s on a datacentre GPU.
# On a 16 GB laptop at 2.4 tok/s the same cap needs ~850s - raise this to 1200
# if you go back to CPU inference.
LLM_REQUEST_TIMEOUT_SECONDS = 600
# Ollama defaults num_ctx to 4096, too small for the genomic prompts, and it
# truncates an over-long prompt SILENTLY rather than erroring - a truncated
# prompt scores badly with nothing to indicate why. The longest criteria text
# in the corpus is 19,676 chars (~4,900 tokens) before the prompt wrapper,
# gene list and oncotree terms are added, so leave real headroom.
# Drop to 8192 only if running on a machine short of memory.
OLLAMA_NUM_CTX = 32768
# Caps output tokens so a runaway generation loop cannot block the pipeline.
# 2048 is too low for real work: on the first GPU run it severed valid JSON
# mid-string at ~1,900 tokens (char 7795, 7089, 8291 across three trials),
# which surfaces as a JSONDecodeError rather than as a truncation. The genomic
# criteria block for a multi-arm trial legitimately runs longer than that.
# 8192 at ~40 tok/s is ~205s, inside LLM_REQUEST_TIMEOUT_SECONDS below.
OLLAMA_NUM_PREDICT = 8192
