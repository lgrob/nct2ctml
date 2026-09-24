# nct2ctml (Kispi fork)

This is a fork of [sumedhasaxena/nct2ctml](https://github.com/sumedhasaxena/nct2ctml),
maintained by Kinderspital Zürich (Kispi) and retargeted from adult oncology in
Hong Kong to paediatric oncology worldwide. It pulls trial records from public
registries, maps their eligibility criteria to the Clinical Trial Markup
Language ([CTML](https://matchminer.gitbook.io/matchminer/deployment/ctml-and-trial-curation))
with a mix of deterministic rules and an LLM, routes the result through human
review, and builds a flat index that Kispi's genomics pipeline joins against
its samples.

CTML remains the curation and review format, and reviewed CTML is still
converted to `ctml/json`. The primary downstream consumer is no longer a
MatchMiner instance but the flat query index described below.

What differs from upstream, and why, is recorded in [CHANGES.md](CHANGES.md).
Upstream is Copyright 2026 The University of Hong Kong under Apache-2.0;
modified files carry a notice at the top.

## Installation

```bash
git clone <this fork> nct2ctml
cd nct2ctml
pip install -r requirements.txt
```

`anthropic` in `requirements.txt` is needed only for the Anthropic backend; it
is imported lazily, so the self-hosted backends run without it.

## Sources

- **ClinicalTrials.gov** (`--source nct`, the default). Queried with a
  paediatric age filter; cached under `cache/nct`, with sync state in
  `cache/nct/trial_status.csv`.
- **EU CTIS**, the Clinical Trials Information System (`--source ctis`).
  Upstream does not cover it. Cached under `cache/ctis`, keyed on the EU CT
  number (e.g. `2025-522006-21-00`). Most CTIS trials have no
  ClinicalTrials.gov record.

`cache/` is gitignored; a fresh clone has no trial data until `pull` runs.

## Usage

Run the CLI from the project root. There are two subcommands, `pull` and
`map`; each requires exactly one of `--all`, `--nct_id` or `--ct_number`.

```bash
python main.py pull --all                          # ClinicalTrials.gov
python main.py pull --all --source ctis            # EU CTIS
python main.py pull --all --source all             # both registries
python main.py pull --nct_id NCT03997435           # one ClinicalTrials.gov trial
python main.py pull --ct_number 2025-522006-21-00  # one CTIS trial (implies --source ctis)

python main.py map --all                           # NCT trials updated within MAPPING_CUTOFF_DAYS
python main.py map --all --cutoff-days 14          # override the cutoff
python main.py map --all --source ctis             # every cached CTIS trial
python main.py map --all --source all              # both registries
python main.py map --all --out /tmp/scratch        # write somewhere other than cache/ctml
python main.py map --nct_id NCT03997435
python main.py map --ct_number 2025-522006-21-00
```

`pull --source` and `map --source` both accept `nct`, `ctis` or `all`;
`map --source` applies only with `--all`. `--cutoff-days` applies only to
`map --all` and overrides `MAPPING_CUTOFF_DAYS` in `config.py` (default 1),
selecting trials by `entry_last_updated_date` in `trial_status.csv`.
`map` writes to `CTML_MAPPED_PATH` in `config.py` (`cache/ctml`) unless `--out`
is given. `map --test_mode` writes to `cache/ctml_test/<date>_<model>`, so
development runs neither overwrite each other nor reach the index.

`map --all` skips trials with no oncology term in their conditions, keywords or
titles (`utils/oncology_scope.py`; `config.SKIP_OUT_OF_SCOPE_AT_MAP`). They
are still pulled and cached. The skipped trials and the reason for each are
listed in `ctml/out-of-scope.tsv`, which `python -m utils.oncology_scope`
regenerates without mapping; a per-trial decision in `ref/scope_overrides.tsv`
wins in either direction. Mapping one trial by id never skips.

`sync_trials.sh` runs `pull --all`, `map --all` and the index build once, for
both registries (`SOURCE=nct ./sync_trials.sh` for one). It activates a conda
environment through a site-specific `~/.init_conda`, so read it before using
it elsewhere.

`ref/local_trial_info.csv` is currently header-only. It is the only route by
which a closed trial is pulled, so while it is empty no closed trials are.

## Workflow

For registry trials:

1. `pull` caches the records under `cache/nct` or `cache/ctis`.
2. `map` writes CTML (YAML) to `cache/ctml/`.
3. A reviewer checks the diagnosis and match criteria and moves the file to
   `ctml/reviewed/`. Unreviewed trials are in the flat index, marked
   `reviewed = 0`; a hit on one is a lead for a curator, not a finding.
4. `python bulk_convert_yaml_to_json.py` converts `ctml/reviewed` to
   `ctml/json` (pass NCT ids to convert only those, `--dry-run` to list
   without writing).

A trial is written to `ctml/needs-review/` (`config.CTML_REVIEW_PATH`) instead
of `cache/ctml/`, for both registries, when the mapper could determine no
Oncotree diagnosis at all (as it stands it would match every patient), or when
a protein change failed its reference check (the criterion is gene-level until
a curator resolves it; the stated value is kept as
`protein_change_unverified`), or when the model returned a gene the criteria
text does not support (`gene_unsupported`; see `trial_genomic.tsv`'s
`gene_check`), or when a diagnosis was answered outside the candidate list the
model was offered (`diagnosis_off_list`). It is held back but not discarded, because a
trial that is absent is one nobody can see is missing.

For local trials not in any registry, a CTML file is written by hand into
`ctml/pending/`, checked, and moved to `ctml/reviewed/`; see
[doc/trial_creation_guide.md](doc/trial_creation_guide.md). The two queues are
kept apart deliberately: `ctml/needs-review` is machine output awaiting a fix,
`ctml/pending` is a colleague's draft awaiting a check.

Mapping details are in [doc/nct_to_ctml_mapping_guide.md](doc/nct_to_ctml_mapping_guide.md).

## Flat query index

CTML is a nested boolean tree, and "does this tree match sample X" cannot be
answered by a query over nested JSON. `utils/build_trial_index.py` flattens the
CTML once, at build time, so a downstream pipeline needs only an equi-join:

```bash
python -m utils.build_trial_index                          # every mapped trial, with review status
python -m utils.build_trial_index --source ctml/reviewed   # reviewed trials only
python -m utils.build_trial_index --strict                 # fail on any unverified protein change
```

By default the index reads three layers, a later one replacing an earlier one
for the same trial: `cache/ctml` (`mapped`), `ctml/needs-review`
(`needs_review`) and `ctml/reviewed` (`reviewed`). `trials.tsv` carries
`review_status`, `reviewed` (0/1) and `source_file`, so a hit on an unreviewed
trial can be routed to a curator rather than into a report. `--source` builds
from one directory instead; its rows are `reviewed` only if it is
`ctml/reviewed`. `--out` is the output directory (default `index`). Outputs:

| File | One row per | Key columns |
|---|---|---|
| `trials.tsv` | trial | `trial_id`, `source`, `nct_id`, `phase`, `status`, `review_status`, `reviewed`, `source_file`, `age_min`/`age_max` with `age_min_inclusive`/`age_max_inclusive` |
| `trial_diagnosis.tsv` | trial, arm, Oncotree node | `oncotree_code`, `oncotree_name`, `source_term`, `from_basket`, `include` |
| `trial_genomic.tsv` | trial, arm, gene criterion | `hugo_symbol`, `variant_category`, `cnv_call`, `protein_change`, `protein_change_stated`, `protein_change_kind`, `protein_refseq`, `protein_ensembl`, `protein_check`, `fusion_partner`, `fusion`, `fusion_partner_check`, `variant_classification`, `include` |
| `manifest.json` | - | row counts, SHA-256 of each output and of `ref/oncotree_file.txt` |

Join samples on `oncotree_code` and `hugo_symbol`. Diagnosis subtrees and the
`_SOLID_`/`_LIQUID_` wildcards are expanded at build time, so a consumer needs
neither the Oncotree hierarchy nor MatchMiner's conventions. Prefer the code to
the display name: codes are stable across Oncotree releases, names are not.
`source_term` keeps the term the curated file states, so a hit can be
explained back to it. The age columns keep the inclusive/exclusive
distinction; the trial-level `age_label` is for display only.

**The index is screening, not decisive.** Rows are the union of everything a
trial could match; exclusions and mixed and/or nesting do not flatten
losslessly. Use the index to narrow the corpus to candidates, then take the
eligibility call from the CTML file, which is the authority. In particular,
`protein_change` is HGVS three-letter notation on the gene's MANE Select
protein (`p.Val600Glu`). That is the same string VEP writes after the
accession in `CSQ_HGVSp`, so it joins on string equality. It is filled only
when `protein_check` is `verified`, meaning every residue it names was found at
that position in `ref/mane_select_proteins.tsv`. Histone H3 is renumbered
from the literature's mature-protein count: `K27M` is `p.Lys28Met`. What the
trial wrote stays in `protein_change_stated`. `--strict` fails the build if
any change does not verify. See `utils/protein_change.py`.

A fusion criterion names its partner when the trial names both genes:
`fusion_partner` and `fusion` in HGNC notation (`EWSR1::FLI1`). The row appears
from both genes' sides when both are panel genes, so match the pair
unordered. An empty partner means any fusion of the gene; a trial listing
example pairs "including but not limited to" keeps its partner-free row too.
Partners are checked against every MANE Select gene plus the IG/TR loci, not
only the panel, because the fusion caller reports off-panel partners such as
RUNX1T1.

`include = 0` rows in `trial_genomic.tsv` are **exclusions** (the CTML
`variant_category` was negated with `!`): a filter that ignores `include`
will report a patient who carries an excluded alteration as a hit.

The build is deterministic - the same inputs give byte-identical outputs - so
the checksums in `manifest.json` identify exactly which trial set produced a
given result. `index/` is gitignored on the assumption that it is regenerated;
if a patient report ever cites it, ship it as a versioned artefact with its
manifest (see CHANGES.md).

## LLM backends

`config.py` selects the backend with `LLM_PLATFORM` and the model with
`LLM_AI_MODEL`; `utils/llm_platforms.py` implements them. The name is matched
case-insensitively.

| `LLM_PLATFORM` | Notes |
|---|---|
| `Anthropic` | **the production backend.** Hosted Claude API through the `anthropic` package, model pinned to `claude-haiku-4-5-20251001`. Reads the key from `ANTHROPIC_API_KEY` (never put a key in `config.py`); `GPU_SERVER_HOSTNAME` is ignored. A prompt's JSON schema is enforced through a forced tool call, at temperature 0 with no thinking. Haiku 4.5 rejects adaptive thinking and the effort parameter, so the platform refuses `ANTHROPIC_THINKING`/`ANTHROPIC_EFFORT` with it before any call. |
| `Ollama` | the GPU backend; served at `GPU_SERVER_HOSTNAME`. Context and output limits come from `OLLAMA_NUM_CTX` and `OLLAMA_NUM_PREDICT`. |
| `SGLang`, `vllm` | self-hosted, OpenAI-style chat endpoint at `GPU_SERVER_HOSTNAME`. |
| `Local_ai` | a stub; raises `NotImplementedError`. |

`LLM_REQUEST_TIMEOUT_SECONDS` bounds every request. To run the mapping on a
Slurm GPU cluster with Ollama under Apptainer, see
[doc/cluster_setup.md](doc/cluster_setup.md) and
`scripts/run_ollama_mapping.sh` (`sbatch scripts/run_ollama_mapping.sh benchmark`
or `... map-all`), which reads the model from `config.py` and refuses to run
unless `LLM_PLATFORM` is `Ollama`.

## Benchmark

`bench/` scores the automated `map` stage against a hand-curated 50-trial
answer key in `ctml/reviewed/`. See [bench/README.md](bench/README.md) for how
the key is built and what the scores mean.

```bash
python -m bench.benchmark_map                    # run the pipeline, then score
python -m bench.benchmark_map --score-only       # score an existing output directory
python -m bench.benchmark_map --conditions-only  # deterministic diagnoses only; no model, no network
```

`--out`, `--truth`, `--limit` and `--json` adjust paths and scope. Diagnoses are
scored two ways: by exact Oncotree name, and by patient population - both
sides expanded to the Oncotree nodes a patient can be coded to - which is the
score that says whether a patient reaches the trial. Genes are scored as exact
`hugo_symbol` sets, and the structure check flags a gene asserted both present
and absent. `--conditions-only` produces no genes or ages, so those are not
scored on that path. Outputs under `bench/output*/` are gitignored; the scored
summary is `bench/report.json`.

## Running tests

```bash
python -m unittest discover -s tests -v            # offline suite
python -m unittest tests.test_reference_validation -v
```

The two live-model tests are skipped by default; they send real prompts to the
backend `config.py` selects, so they need a running server or an API key:

```bash
RUN_LIVE_LLM_TESTS=1 python -m unittest tests.test_ai_helper -v
```

## Reference data

| File | What it is |
|---|---|
| `ref/oncotree_file.txt` | Oncotree tab-delimited export, `oncotree_2025_10_03` (879 names). Placed by hand; no script fetches it. A test pins the count and the documented version. |
| `ref/genes.txt` | Kispi's paediatric gene panel, 1,086 current HGNC symbols. The accept-list for `hugo_symbol`. |
| `ref/genes_kispi.txt` | the panel as Kispi supplied it (1,092 symbols); its difference from `genes.txt` defines which retired spellings may be rewritten. |
| `ref/synonym_to_gene_symbol.tsv` | gene aliases from NCBI Gene, rebuilt by `utils/build_gene_synonyms.py`. |
| `ref/gene_synonym_addendum.tsv` | case variants, multi-gene aliases, and a `!` blocklist. |
| `ref/synonym_collisions.tsv` | aliases claimed by more than one gene, quarantined rather than guessed. |
| `ref/diagnosis_synonyms.tsv` | curated registry disease spellings that folding cannot reach, each with its reason. |
| `ref/mane_genes.tsv` | symbol and HGNC id of every MANE Select v1.5 gene (19,364); validates fusion partners. Written by the same builder. |
| `ref/scope_overrides.tsv` | per-trial overrides of the map-time oncology scope filter, each with its reason. |
| `ref/mane_select_proteins.tsv` | MANE Select GRCh38 v1.5 protein sequences for the panel and every histone H3 gene, with RefSeq and Ensembl accessions; the header records each source file's SHA-256. Rebuilt per MANE release with `python -m utils.build_protein_reference --release 1.5`. |

`ref/Census_gene_list.csv` (COSMIC) is untracked because its licence restricts
redistribution; nothing reads it at runtime.

## Known limitations

Open correctness issues, unmeasured guesses and upstream assumptions still
carried are listed in [doc/open_issues.md](doc/open_issues.md).

## Citation

If you use nct2ctml, please cite:

Sumedha Saxena, Edmond S K Ma, Aya El Helali, David J H Shih. AI-assisted patient matching for
personalized cancer medicine. Briefings in Bioinformatics.
2025;26(Supplement_1):i12–i14. https://doi.org/10.1093/bib/bbaf631.013

```bibtex
@article{saxena2025nct2ctml,
  title   = {AI-assisted patient matching for personalized cancer medicine},
  author  = {Saxena, Sumedha and Ma, Edmond S K and El Helali, Aya and Shih, David J H},
  journal = {Briefings in Bioinformatics},
  volume  = {26},
  number  = {Supplement_1},
  pages   = {i12--i14},
  year    = {2025},
  doi     = {10.1093/bib/bbaf631.013},
  url     = {https://academic.oup.com/bib/article/26/Supplement_1/i12/8378037}
}
```

## License

This project's source code is licensed under the Apache License 2.0.
See [LICENSE](LICENSE). Modifications are described in [CHANGES.md](CHANGES.md).

## Resources

- [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api#extapi)
- [EU Clinical Trials Information System](https://euclinicaltrials.eu/)
- [MatchMiner CTML](https://matchminer.gitbook.io/matchminer/deployment/ctml-and-trial-curation)
- [Oncotree (oncotree_2025_10_03)](https://oncotree.mskcc.org/?version=oncotree_2025_10_03&field=NAME)
- [Manual CTML curation guide](doc/trial_creation_guide.md)
