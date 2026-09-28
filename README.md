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

Python 3.12 or newer (`pyproject.toml`; tested on 3.12 and 3.13). Install
from the lock file, which pins every package at the version the test suite
was run with:

```bash
git clone <this fork> nct2ctml
cd nct2ctml
python3.12 -m venv .venv
./.venv/bin/pip install -r requirements.lock
```

`requirements.txt` states only the minimum versions (the same as
`pyproject.toml`). Use it to try newer packages, not to reproduce a run.
After changing it, regenerate the lock as its header describes;
`tests/test_environment.py` fails while the three files disagree. Each run
records the Python and package versions it used in `runs/<run_id>/run.json`.

`anthropic` is needed only for the Anthropic backend; it is imported lazily,
so the self-hosted backends run without it.

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
both registries (`SOURCE=nct ./sync_trials.sh` for one). It uses
`./.venv/bin/python` unless `PYTHON` names another interpreter, and does not
create or update the environment. It stops at the first failing step and runs
only one sync at a time: a second one started while the first is running
exits with status 75 (the lock is `cache/sync.lock`, and a lock left behind by
a killed run is taken over). It can be started from any directory, as cron
does.

`ref/local_trial_info.csv` is currently header-only. It is the only route by
which a closed trial is pulled, so while it is empty no closed trials are.

## Workflow

For registry trials:

1. `pull` caches the records under `cache/nct` or `cache/ctis`.
2. `map` writes CTML (YAML) to `cache/ctml/`.
3. A reviewer checks the diagnosis and match criteria and moves the file to
   `ctml/reviewed/`. Unreviewed trials are in the flat index, marked
   `reviewed = 0`; a hit on one is a lead for a curator, not a finding.
4. `python main.py promote` converts `ctml/reviewed` to `ctml/json`, the
   queue `matchminer-admin` loads into MatchMiner (pass trial ids to convert
   only those, `--dry-run` to list without writing). It used to be
   `bulk_convert_yaml_to_json.py`. The `_provenance` block is left out of the
   JSON, because MatchMiner rejects unknown fields.

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

## Reviewing flagged trials

`utils/review_helper.py` puts the evidence for each flag next to the flag and
makes accepting a reviewed trial a checked, logged step. It reads the same
reference data as the mapper and never calls a model. Run it from the repo
root with the repo's environment (`source .venv/bin/activate`, or call
`./.venv/bin/python` directly); a Python without the repo's requirements
fails with `No module named 'loguru'`.

```
python -m utils.review_helper queue                      # ctml/needs-review with reasons
python -m utils.review_helper sheets                     # one HTML sheet per queued trial
python -m utils.review_helper audit --n 60               # random mapped trials (roadmap 3.4)
python -m utils.review_helper check NCT05843253          # what accept would still refuse
python -m utils.review_helper accept NCT05843253 --reviewer <name> [--note "..."]
python -m utils.review_helper exclude NCT05843253 --reviewer <name> --reason "..."
python -m utils.review_helper flag-exclusions [--apply]  # see below
python -m utils.review_helper flag-gene-status [--apply] # genes required although the text says absent
```

**Excluded diagnoses.** Write `oncotree_primary_diagnosis: '!Name'` (quoted:
a bare leading `!` is a YAML tag) beside the diagnosis a trial enrols to
exclude a subtype, e.g. AML without APL. The index publishes the excluded node
and its descendants with `include = 0` and leaves them out of the eligible
rows. `accept` refuses a trial whose only diagnoses are excluded ones.

**Diagnoses named only in the exclusion criteria** (`diagnosis_excluded`).
The mapper flags a diagnosis that the exclusion criteria name and that the
inclusion criteria, title and conditions do not, and routes the trial to
review. `flag-exclusions` applies the same check to CTML already written;
with `--apply` it adds the flag and moves mapped trials to the review queue.
`ctml/reviewed` is never touched.

`exclude` takes a trial out of scope: it adds a `skip` row with the reason to
`ref/scope_overrides.tsv` and logs it in `ctml/review_log.tsv`. `map --all`
then no longer maps the trial, and the index build drops it from every layer
(listed under `excluded_by_scope_override` in `manifest.json`). Its YAML files
stay where they are. Rebuild the index to apply it.

Open `review_sheets/index.html` (git-ignored). Each sheet lists every flag with
what resolves it and the passages that mention the item. For a flagged gene
the sheet says which of these applies: named in the trial text but not in the
arm's criteria (the mapper checks each arm's own text), only an ambiguous NCBI
alias (such as ALL for BCR, shown but never counted as support), only a
near-miss spelling (KTM2A), or not named at all. Diagnoses are marked as named
in the text, parent named, or not named. Protein changes show the residue the
reference protein carries.

To resolve a trial, edit its YAML in `ctml/needs-review/`: delete a flag key
to confirm its item, or delete the item. Then run `accept`. It refuses a file
that still carries a flag, has no diagnosis, names a gene or diagnosis outside
the reference data, or has a protein change that fails its reference check.
On success it stamps `curated_on`, moves the file to `ctml/reviewed/` and
appends a line to `ctml/review_log.tsv`: date, trial, reviewer, the flags
resolved and the file's SHA-256. The audit command writes
`ctml/audit_<date>.tsv` for the verdicts, and sheets to `review_sheets/audit/`.

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
`ctml/reviewed`. `--out` is the output directory (default `index`).

A trial sent to `ctml/needs-review` by one run and mapped cleanly by a later
one keeps its review copy: the mapper never deletes it, because a curator may
be editing it. The index still publishes the review copy, sets
`layer_conflict = newer_mapped_copy` and lists the pair in
`layer_conflicts.tsv`. Resolve it by removing the review copy, or by moving
the curated file to `ctml/reviewed/`. "Newer" is judged by file modification
time, so a copy that resets times can hide a conflict.

When a later run sends a trial to review again and its new mapping differs
from the copy already in `ctml/needs-review`, the old copy is kept as
`<trial>.yaml.prev` (then `.prev.1`, `.prev.2`, ...; a backup is never
overwritten) before the new one is written. The index skips these files and
lists them under `review_backups` in `manifest.json`.

Outputs:

| File | One row per | Key columns |
|---|---|---|
| `trials.tsv` | trial | `trial_id`, `source`, `nct_id`, `phase`, `status`, `review_status`, `reviewed`, `source_file`, `layer_conflict`, `age_min`/`age_max` with `age_min_inclusive`/`age_max_inclusive`, `genes_not_required`, `mapped_at`, `mapped_run`, `mapped_commit`, `llm_model`, `prompt_settings` |
| `trial_diagnosis.tsv` | trial, arm, Oncotree node | `oncotree_code`, `oncotree_name`, `source_term`, `from_basket`, `include` |
| `trial_genomic.tsv` | trial, arm, gene criterion | `hugo_symbol`, `variant_category`, `cnv_call`, `protein_change`, `protein_change_stated`, `protein_change_kind`, `protein_refseq`, `protein_ensembl`, `protein_check`, `fusion_partner`, `fusion`, `fusion_partner_check`, `variant_classification`, `include` |
| `layer_conflicts.tsv` | trial | trials whose published `ctml/needs-review` copy is older than a clean mapping in `cache/ctml`: both files and their modification times |
| `manifest.json` | - | row counts, SHA-256 of each output and of every reference file, the build's commit, `layer_conflicts` count, `review_backups` list, trials per mapping setup and per commit, `reference_drift` |

`genes_not_required` lists genes the text mentions that the model judged not required of every patient (risk group, one cohort, conditional, an alternative route, an example, expression or germline), each with its role. They are not matched on; show them to the clinician beside the trial. Trials carrying only this note are published, not queued for review (roadmap 2.9, option A).

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
given result. `index/` itself is a working copy: every sync overwrites it,
and by default it includes trials nobody has reviewed. An index a report
cites must be a release.

### Index releases

A release is a frozen, numbered index that can be cited in a report and
rebuilt later from git alone (`utils/release_index.py`):

```bash
python -m utils.release_index create                   # tag index-YYYY.MM.DD[.N] at HEAD
python -m utils.release_index verify releases/index-2026.10.01.tar.gz --rebuild
```

`create` refuses to run unless the checkout is clean (no uncommitted or
untracked files, so every input is in the commit) and `ref/` matches
`ref/SOURCES.tsv`. It then:

1. builds from `ctml/reviewed` only, with `--strict`;
2. writes `release.json`: the commit, the SHA-256 of every reviewed CTML
   file, every reference file and every output;
3. packs it with the four tables and `manifest.json` into
   `releases/<tag>.tar.gz`, byte for byte reproducible, plus a `.sha256`
   file;
4. creates an annotated git tag at HEAD whose message records the
   archive's SHA-256 and every output's.

`verify` checks an archive against its `.sha256` file, `release.json` and the
tag. The tag is the one record not stored beside the archive, so rewriting
all three together still fails. `--rebuild` builds again from the tagged
commit in a temporary worktree and requires byte-identical outputs.

Nothing leaves the machine until you publish: `create` tags locally and
prints the commands to push the tag and upload the archive (a GitHub
Release, or Kispi storage). `releases/` is gitignored.

For the consuming pipeline: read the tables from an extracted release, never
from `index/`; check the archive with its `.sha256`; and write the tag (for
example `index-2026.10.01`) into every report that uses a match. "Why did
this sample match that trial?" is then answered by that release's CTML at
that commit.

## Provenance and replay

Every mapped file ends with a `_provenance` block (`utils/provenance.py`)
saying what produced it: run id, time, git commit and whether the tree had
local changes, LLM platform, model and settings, both prompt variants
(`GENOMIC_PROMPT`, `DIAGNOSIS_INPUT`), and the SHA-256 of every reference
file. Review keeps it; the index publishes it in `trials.tsv`, and its
manifest counts trials mapped against a reference file other than the
current one (`reference_drift`).

Each `map` and benchmark run also writes `runs/<run_id>/`:

| File | What it is |
|---|---|
| `run.json` | command, code version, model and settings, reference hashes, Python and package versions; call counts once the run ends |
| `llm_calls.jsonl` | one line per model call: trial, prompt, prompt and schema SHA-256, raw response (for Anthropic with request id, answering model and token usage), time taken, or the error |
| `schemas/<sha256>.json` | each distinct schema, exactly as sent |

A full run is about 50 MB (estimated). `runs/` is gitignored but, unlike
`cache/`, cannot be regenerated: it is the only copy of what the model
answered. Keep the run a published result was built from. `RUNS_PATH = None`
in `config.py` turns recording off.

To rebuild a run's CTML without a model, answer from its record:

```bash
NCT2CTML_LLM_PLATFORM=Replay NCT2CTML_REPLAY_FILE=runs/<run_id>/llm_calls.jsonl \
    python main.py map --nct_id NCT03643276 --out /tmp/replay
```

Each call is looked up by the hash of its prompt and schema and answered
with the recorded response. A prompt the run never sent, because the code
or its inputs have changed since, fails that trial with `ReplayMiss`. So a
replay that completes shows that the deterministic code still does what it
did, and a diff against the original isolates what changed outside the model.

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
| `Replay` | answers from a recorded run instead of a model; see [Provenance and replay](#provenance-and-replay). |

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

GitHub Actions runs the suite on Python 3.12 and 3.13 on every push
(`.github/workflows/tests.yml`), installed from `requirements.lock` and
`requirements-dev.txt`. The job also runs the benchmark regression check
(`bench/README.md`). `cache/` is not in git, so CI uses frozen
ClinicalTrials.gov records from `tests/fixtures/registry/nct`. Tests that
need CTIS records skip there: whether those may be republished is not
settled (`tests/fixtures/registry/README.md`).

## Linting and formatting

[ruff](https://docs.astral.sh/ruff/) lints and formats the code (its
formatter replaces Black). The rules are in `pyproject.toml`, and the version
is pinned in `requirements-dev.txt`, because a different ruff can format
differently. GitHub Actions runs both checks on every push and pull request
(`.github/workflows/lint.yml`).

```bash
./.venv/bin/pip install -r requirements-dev.txt
ruff check .                  # lint; --fix applies the safe fixes
ruff format .                 # format in place; --check only reports
pip install pre-commit && pre-commit install   # run both on every commit
git config blame.ignoreRevsFile .git-blame-ignore-revs   # blame past the reformat
```

The whole repository was reformatted in one commit, listed in
`.git-blame-ignore-revs`. GitHub's blame skips it automatically. A plain
merge from upstream would now conflict almost everywhere, so merge upstream
with:

```bash
python scripts/merge_upstream.py              # upstream/main, or pass a ref
```

It merges each file three ways after putting both the merge base and
upstream's version through the same ruff steps, so only real changes can
conflict. On a simulated upstream update touching three files, a plain merge
conflicted in 2 files, formatting upstream's tip alone conflicted in 24, and
the script conflicted in 1: the function both sides had really changed. A
conflict leaves the merge in progress, with the files unstaged, for you to
resolve.

## Reference data

| File | What it is |
|---|---|
| `ref/SOURCES.tsv` | where every other file here comes from: kind, source, version, date retrieved and, for files that come from outside, the pinned SHA-256. See below. |
| `ref/oncotree_file.txt` | Oncotree tab-delimited export, `oncotree_2025_10_03` (879 names). Fetched with `python -m utils.verify_refs --fetch-oncotree <version>`. A test pins the count and the documented version. |
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

`python -m utils.verify_refs` checks `ref/` against `ref/SOURCES.tsv`, in CI
on every push and in `tests/test_reference_sources.py`. Every file must be
listed. Files that come from outside (fetched, built or supplied) are pinned
by SHA-256, so one replaced without its fetch or build step fails. After a
deliberate rebuild, re-pin it in the same commit with
`python -m utils.verify_refs --update <file>`. Curated files are not pinned;
git records their edits. `--online` compares `ref/oncotree_file.txt` with the
Oncotree API. The API does not serve a version byte for byte the same over
time: it now gives `oncotree_2025_10_03` a different layout and two extra
cross-reference codes for SRCCR. So only a difference in the tree fails;
metadata differences are shown as notes. GitHub runs the online check weekly.

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
