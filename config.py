# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

import os

# Every tunable setting below can be overridden from the environment as
# NCT2CTML_<NAME>, e.g. NCT2CTML_LLM_AI_MODEL=llama3.3:70b. What was overridden
# is kept in OVERRIDES: main.py logs it at startup and each run records it in
# runs/<run_id>/run.json, so a setting changed from outside the file is never
# invisible. Paths are not overridable: the reference files are checked
# against ref/SOURCES.tsv, and the layer directories are fixed by the layout.
OVERRIDES: dict[str, object] = {}
_TRUE, _FALSE = {"1", "true", "yes", "on"}, {"0", "false", "no", "off"}


def _env(name, default, cast=str, env=None):
    """The setting's value: NCT2CTML_<env or name> if set, else the default."""
    key = f"NCT2CTML_{env or name}"
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        if cast is bool:
            if raw.lower() not in _TRUE | _FALSE:
                raise ValueError("expected one of 1/0, true/false, yes/no, on/off")
            value = raw.lower() in _TRUE
        elif cast == "optional":
            value = None if raw.lower() in ("", "none", "null") else raw
        else:
            value = cast(raw)
    except ValueError as e:
        raise ValueError(f"{key}={raw!r}: {e}") from None
    OVERRIDES[name] = value
    return value


# 127.0.0.1 rather than localhost or 0.0.0.0: proxied sites list
# 127.0.0.1 in NO_PROXY, and a client aimed at 0.0.0.0 gets routed to the
# proxy, which cannot reach a port on the compute node.
GPU_SERVER_HOSTNAME = _env("GPU_SERVER_HOSTNAME", "http://127.0.0.1")

# Options: Local_ai, vllm, SGLang, Ollama, Anthropic, Replay
# NCT2CTML_LLM_PLATFORM overrides it (e.g. Replay, or Ollama on the GPU
# cluster); every mapped file records the platform it was made with.
LLM_PLATFORM = _env("LLM_PLATFORM", "Anthropic")

# Provenance (utils/provenance.py). Each `map` and benchmark run writes
# RUNS_PATH/<run_id>/run.json and records every model call, prompt and raw
# answer, in RUNS_PATH/<run_id>/llm_calls.jsonl. Unlike cache/ it cannot be
# regenerated: it is the only copy of what the model said. None turns
# recording off; the CTML is still stamped with its _provenance block.
RUNS_PATH = _env("RUNS_PATH", "runs", "optional")
# LLM_PLATFORM = "Replay" answers from a recorded run instead of a model,
# which rebuilds that run's CTML offline. Point this at its llm_calls.jsonl.
LLM_REPLAY_FILE = _env("LLM_REPLAY_FILE", None, "optional", env="REPLAY_FILE")

# Anthropic (hosted Claude API) settings - the production backend since
# 2026-09-24 (roadmap D1). Auth comes from the ANTHROPIC_API_KEY environment
# variable - do not put a key here. GPU_SERVER_HOSTNAME is ignored.
#
# Claude Haiku 4.5, pinned to its dated snapshot so a run is reproducible:
# an alias can move to new weights under the same name. Every prompt
# measurement in doc/decisions/ and doc/changelog.md from 2026-09-23 on (age bounds, fusion partners,
# the stage-2 baseline) was made on this snapshot, with the request shape
# utils/llm_platforms.AnthropicPlatform sends: JSON through a forced tool
# call, no thinking. It is also the cheapest current Claude model ($1/$5 per
# 1M tokens). Moving to another model is a roadmap step 2.3 decision, taken
# on replicated benchmark numbers, not a config edit.
LLM_AI_MODEL = _env("LLM_AI_MODEL", "claude-haiku-4-5-20251001")
# Thinking and effort. Haiku 4.5 supports neither adaptive thinking nor the
# effort parameter (the API rejects the request), so both are off; the
# platform refuses the combination rather than failing mid-run. On models
# that support them, set ANTHROPIC_THINKING = "adaptive" and an effort level.
ANTHROPIC_THINKING = _env("ANTHROPIC_THINKING", None, "optional")  # None | "adaptive"
# None | low | medium | high | xhigh | max
ANTHROPIC_EFFORT = _env("ANTHROPIC_EFFORT", None, "optional")
# 0 for reproducibility. Ignored when thinking is on (the API requires 1).
ANTHROPIC_TEMPERATURE = _env("ANTHROPIC_TEMPERATURE", 0, float)

# What text the diagnosis step is given (roadmap 2.8, 2026-09-26). The model
# was handed exclusion criteria alongside inclusion criteria - for CTIS with
# no labels at all - and returned excluded diagnoses as eligible ones (75
# trials in the first full run).
#   legacy          - as before: NCT "Inclusion Criteria: ... Exclusion
#                     Criteria: ...", CTIS conditions + both sections unlabelled
#   labelled        - both sections labelled for both registries, and the
#                     prompt says exclusion diagnoses are exclusions
#   inclusion_only  - title, conditions and inclusion criteria only (arm
#                     level: the arm's inclusion criteria)
# NCT2CTML_DIAGNOSIS_INPUT overrides it (used by the measurement harness).
# Default "labelled" since 2026-09-27 (3 replicates, 123 trials): exclusion-only
# diagnoses 113 -> 57, recall unchanged; inclusion_only lost 16 curated
# diagnoses and was rejected. See doc/decisions/2026-09-27-2.8-diagnosis-input.md.
DIAGNOSIS_INPUT = _env("DIAGNOSIS_INPUT", "labelled")
# Inclusion genomic prompt (roadmap 2.9): "baseline" (unchanged), "rules"
# (explicit rules: only genes every entering patient must carry) or "roles"
# (each gene is classified; only requirements enter the match tree, the rest
# are recorded as gene_role_dropped and route the trial to review).
# "roles_union" (2.9b, measured 2026-09-28 and NOT adopted: +1 requirement,
# +5 restrictive trials, review load unchanged): roles plus cohort_union.
# NCT2CTML_GENOMIC_PROMPT overrides it (used by the measurement harness).
# Default "roles" since 2026-09-28 (roadmap 2.9, 370 trials x 3 replicates):
# trials requiring a gene of every patient that the text does not require
# 191 -> 86; every gene kept out is recorded for review. See
# doc/decisions/2026-09-28-2.9-genomic-prompt-roles.md.
GENOMIC_PROMPT = _env("GENOMIC_PROMPT", "roles")
ANTHROPIC_MAX_TOKENS = _env("ANTHROPIC_MAX_TOKENS", 16000, int)

# Other models tried, and the notes on each (GPU sizes, benchmark scores, why
# not adopted): doc/llm_backends.md, "Models tried". To switch, set
# NCT2CTML_LLM_PLATFORM and NCT2CTML_LLM_AI_MODEL; every run records both.


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
# Where `main.py map` writes machine output, and where curator-signed trials
# live. The flat index reads mapped, then needs-review, then reviewed; a later
# layer replaces an earlier one for the same trial (utils/build_trial_index.py).
CTML_MAPPED_PATH = "cache/ctml"
CTML_REVIEWED_PATH = "ctml/reviewed"
# Where the pull stage caches raw registry records, one JSON per trial, keyed
# by NCT id or EU CT number. The benchmark reads both, because 5 of the 55
# curated keys in ctml/reviewed are CTIS trials.
NCT_CACHE_PATH = "cache/nct"
CTIS_CACHE_PATH = "cache/ctis"
# Bulk mapping skips trials with no oncology term (utils/oncology_scope.py).
# Mapping a single trial by id never skips. Per-trial decisions go in the
# overrides file; the skipped trials are listed, with reasons, in the report.
SKIP_OUT_OF_SCOPE_AT_MAP = _env("SKIP_OUT_OF_SCOPE_AT_MAP", True, bool)
SCOPE_OVERRIDES_FILE_PATH = "ref/scope_overrides.tsv"
SCOPE_REPORT_FILE_PATH = "ctml/out-of-scope.tsv"

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
# Aliases the output side (canonical_gene) must never rewrite, although the
# synonym table maps each unambiguously to a panel gene: JMML, CHOP, PD-1.
# Only the rewrite reads it; the input-side search is unaffected.
GENE_REWRITE_EXCLUSION_FILE_PATH = "ref/gene_rewrite_exclusions.tsv"
# MANE Select protein sequences every trial protein change is checked
# against (utils/protein_change.py); built by utils/build_protein_reference.py.
PROTEIN_REFERENCE_FILE_PATH = "ref/mane_select_proteins.tsv"
# How eligibility text names a diagnosis; text matching only (src/text_rules.Reference).
DIAGNOSIS_TEXT_TERMS_FILE_PATH = "ref/diagnosis_text_terms.tsv"
# Cytogenetic rearrangement -> gene pair, curated with a reason per row;
# read only by utils/translocations.py.
TRANSLOCATION_TABLE_FILE_PATH = "ref/translocation_fusions.tsv"
# Every gene with a MANE Select transcript, symbol and HGNC id. Not an
# accept-list for hugo_symbol (that is the panel); it validates fusion
# partners, which are often off-panel (RUNX1T1, SET) yet reported by the
# fusion caller. Built by the same script as the protein reference.
MANE_GENES_FILE_PATH = "ref/mane_genes.tsv"
# Registry disease spellings that folding cannot reach - lineage decisions,
# WHO reclassifications and registry house style. See the header of the file
# itself for what belongs in it and what does not.
DIAGNOSIS_SYNONYM_FILE_PATH = "ref/diagnosis_synonyms.tsv"
# Short condition strings the conditions seed must never resolve to a diagnosis,
# because the abbreviation means something else (GCT, RAS). See the file header.
DIAGNOSIS_ABBREV_EXCLUSION_FILE_PATH = "ref/diagnosis_abbrev_exclusions.tsv"

# Mapping configuration
# Number of days back to consider for mapping trials
# Trials with entry_last_updated_date within this many days will be mapped
MAPPING_CUTOFF_DAYS = _env("MAPPING_CUTOFF_DAYS", 1, int)
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
LLM_REQUEST_TIMEOUT_SECONDS = _env("LLM_REQUEST_TIMEOUT_SECONDS", 600, int)
# Ollama defaults num_ctx to 4096, too small for the genomic prompts, and it
# truncates an over-long prompt SILENTLY rather than erroring - a truncated
# prompt scores badly with nothing to indicate why. The longest criteria text
# in the corpus is 19,676 chars (~4,900 tokens) before the prompt wrapper,
# gene list and oncotree terms are added, so leave real headroom.
# Drop to 8192 only if running on a machine short of memory.
OLLAMA_NUM_CTX = _env("OLLAMA_NUM_CTX", 32768, int)
# Caps output tokens so a runaway generation loop cannot block the pipeline.
# 2048 is too low for real work: on the first GPU run it severed valid JSON
# mid-string at ~1,900 tokens (char 7795, 7089, 8291 across three trials),
# which surfaces as a JSONDecodeError rather than as a truncation. The genomic
# criteria block for a multi-arm trial legitimately runs longer than that.
# 8192 at ~40 tok/s is ~205s, inside LLM_REQUEST_TIMEOUT_SECONDS below.
OLLAMA_NUM_PREDICT = _env("OLLAMA_NUM_PREDICT", 8192, int)
# Largest candidate list the prompts send as a JSON-schema enum (utils/llm/schema), per
# LLM_PLATFORM (lower-case key; a platform not listed gets 400). Above it the
# enum is dropped, the shape is still enforced and off-list answers become
# possible again, so utils/llm/schema logs a WARNING and counts it.
#
# 400 is kept for the self-hosted backends. They compile the schema into a
# decoding grammar (llama.cpp for Ollama and LocalAI, xgrammar/outlines for
# vLLM and SGLang), and one with hundreds of alternatives is slow to build.
# The value is a guard, never measured on the GPU.
#
# None (never drop) for Anthropic, for two reasons. The request is a forced
# tool call without `strict: true`, so no grammar is compiled at all - the
# enum is guidance the model follows, not a decoding constraint - and the cap
# guarded against a cost this backend does not pay. Should strict tool use be
# switched on, Anthropic's structured-outputs documentation (read 2026-09-24)
# lists no enum-size limit; its limits are 20 strict tools, 24 optional and
# 16 union-typed parameters, plus internal grammar-size limits, and those
# fail loudly with a 400 "schema is too complex" rather than silently. The
# largest list the diagnosis path can build is all 847 Oncotree descendants.
# Measured 2026-09-24: over the 1,255 cached trials the seed branch floor
# alone reaches 438 on NCT02508038 (six forced branches), and the floor plus
# its largest missing level-1 branch exceeds 320 on 33 trials, so 400 was
# no longer a bound the diagnosis path stays under.
SCHEMA_ENUM_MAX_VALUES = {
    "ollama": 400,
    "local_ai": 400,
    "vllm": 400,
    "sglang": 400,
    "anthropic": None,
}
# Lists above this fraction of the cap are logged at INFO, so a run shows the
# cap being approached before it is crossed.
SCHEMA_ENUM_NEAR_CAP_FRACTION = _env("SCHEMA_ENUM_NEAR_CAP_FRACTION", 0.8, float)
