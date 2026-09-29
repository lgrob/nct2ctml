# Improvement plan

Code quality, documentation and reproducibility work, from a review on
2026-09-28 at commit `d61a30c`. Tick a step when it is done and note the
commit next to it. Priority is provenance first: outputs mapped before it is
in place cannot be traced back to what produced them.

Baseline at the time of the review: 543 offline tests pass in ~13 s
(3 skipped); ruff reports 1,947 findings, mostly style.

## Phase 1 - Reproducibility and provenance

- [x] **1. Stamp provenance into every mapped CTML file.**
  A file in `cache/ctml/` does not say which model, prompt variant or code
  version produced it, while `NCT2CTML_GENOMIC_PROMPT` and
  `NCT2CTML_DIAGNOSIS_INPUT` can change the prompts through the environment.
  Add a block at the write in [src/trial_map_manager.py](../src/trial_map_manager.py)
  (the `yaml.dump` near line 386):
  ```yaml
  _provenance:
    mapped_at: 2026-09-28T...
    git_commit: d61a30c        # plus a dirty flag
    llm_platform: Anthropic
    llm_model: claude-haiku-4-5-20251001
    genomic_prompt: roles
    diagnosis_input: labelled
    ref_sha256: {genes.txt: ..., synonym_to_gene_symbol.tsv: ..., oncotree_file.txt: ...}
  ```
  `review_helper accept` keeps it; the index carries it into `trials.tsv`.

- [x] **2. Complete the index manifest.**
  [utils/build_trial_index.py](../utils/build_trial_index.py) (`manifest = {`,
  near line 555) hashes only Oncotree and the protein reference. Add every
  `ref/` file the mapper or the build reads (genes, synonyms, addendum,
  translocations, MANE genes, scope overrides), the git commit and dirty flag,
  and a count of trials per model and prompt from step 1.

- [x] **3. Record raw LLM exchanges.**
  Temperature 0 on a hosted model does not guarantee determinism, and
  [utils/llm_platforms.py](../utils/llm_platforms.py) records nothing. Append
  one JSONL record per call: prompt hash, schema hash, model, request ID, raw
  response, token usage. A CTML file can then be rebuilt offline from recorded
  answers, and an odd output traced to the exact answer. Relevant to the IVDR
  audit trail.

  Steps 1-3 done 2026-09-28 (see doc/changelog.md, "Provenance"), including replay:
  `NCT2CTML_LLM_PLATFORM=Replay NCT2CTML_REPLAY_FILE=runs/<id>/llm_calls.jsonl`.

- [x] **4. Pin the environment.**
  - `pyproject.toml` with `requires-python` (`.venv` runs 3.13,
    [sync_trials.sh](../sync_trials.sh) creates 3.12).
  - Keep `requirements.txt` as floors; add a lock file (`uv lock` or
    `pip-compile`) with the versions actually run, e.g. `anthropic==1.4.0`,
    `pydantic==2.13.5`.
  - `sync_trials.sh`: `set -euo pipefail`, no dependency on `~/.init_conda`
    (take the interpreter from a variable), and `flock` so two cron runs
    cannot overlap.

  Done 2026-09-28: `pyproject.toml`, `requirements.lock` (from the tested
  venv; no uv or pip-compile here, so no hashes), `tests/test_environment.py`,
  and `sync_trials.sh` with a `mkdir` lock (macOS has no `flock`).

- [x] **5. Add a fetch/verify script for reference data.**
  `ref/oncotree_file.txt` is "placed by hand; no script fetches it". Add
  `ref/SOURCES.tsv` (file, upstream URL, version, retrieved on, SHA-256) and
  `python -m utils.verify_refs`, and run it as a test so a silently replaced
  file fails CI.

  Done 2026-09-28: `ref/SOURCES.tsv`, `utils/verify_refs.py` (check, `--update`,
  `--online`, `--fetch-oncotree`), `tests/test_reference_sources.py`, and
  `.github/workflows/reference-data.yml`. Curated files are listed but not
  pinned. Found: the Oncotree API does not serve a version byte for byte the
  same over time, and name-keyed parents (`doc/open_issues.md`).

- [x] **6. Treat the index as a release.**
  One command (e.g. `make release`) that builds from `ctml/reviewed` with
  `--strict`, tags the commit, and archives `index/` with its manifest - the
  step `.gitignore` already asks for once a patient report cites the index.

  Done 2026-09-28: `python -m utils.release_index create` / `verify --rebuild`
  (README, "Index releases"). Not yet done, and outside this repo: the
  genomics pipeline reading a release instead of `index/` and writing the tag
  into reports; publishing the first release.

## Phase 2 - Code quality

- [x] **7. Linting, in two commits.**
  1. `[tool.ruff]` in `pyproject.toml`, `select = ["F", "E", "W", "B", "I", "UP"]`,
     `ignore = ["E501"]`; run `ruff check --fix` and `ruff format` in one
     commit and list it in `.git-blame-ignore-revs`.
  2. Fix the real findings by hand:
     - 12 unused imports (`ruff check --select F401`)
     - unused `original_keys` in [tests/test_trial_data_helper.py](../tests/test_trial_data_helper.py) (~line 604)
     - `zip()` without `strict=` in [utils/review_helper.py](../utils/review_helper.py) (~line 570)
       and [utils/build_protein_reference.py](../utils/build_protein_reference.py) (~line 94)
     - duplicate set member in [tests/test_prompt_determinism.py](../tests/test_prompt_determinism.py) (~line 57)

  Done 2026-09-28 (`45c08b6`, `04c8de4`), with the lint half of step 8
  (`.github/workflows/lint.yml`, pre-commit) and
  `scripts/merge_upstream.py` for upstream merges after the reformat.

- [x] **8. CI.**
  GitHub Actions or GitLab CI running ruff, the offline unittest suite,
  `python -m bench.benchmark_map --conditions-only` as a regression check (no
  model, no network), and the reference check from step 5. A `pre-commit`
  config runs the same checks locally.

  Done 2026-09-28. Workflows: `lint.yml`, `reference-data.yml` (step 5) and
  `tests.yml` (the suite on 3.12 and 3.13, plus `bench.conditions_baseline`
  on frozen NCT fixtures). **Open:** CTIS fixtures, pending whether sponsor
  records from CTIS may be republished. Until then, 4 CTIS tests skip in CI.

- [x] **9. Remove dead and orphaned code.**
  - [x] Delete `src/get_all_intervention_types.py`
        (one-off script, broken import path).
  - [x] Delete `rag/` (two upstream notebooks, referenced nowhere) or move it
        to `archive/` with a note.
  - [x] `git rm yaml/.DS_Store`; add `.DS_Store` to `.gitignore`.
  - [x] Move `tests/determinism_probe.py` out of `tests/` (a helper, not a test).
  - [x] Move `bulk_convert_yaml_to_json.py` into `utils/` or behind a
        `main.py` subcommand.
  - [x] Remove the 19 `print()` calls in tests.

  Done 2026-09-28. The converter turned out to be live (`matchminer-admin`
  reads `ctml/json`), so it became `python main.py promote`
  (`utils/promote.py`) rather than being removed. The probe is in `scripts/`.
  `tests/test_ctml_conversion.py` was deleted too: 24 live `map` calls with no
  assertions, which pytest would collect.

- [x] **10. Slim down `config.py`.**
  Move the ~60 lines of commented-out alternative models to `doc/` (with the
  model benchmark notes). Keep the active settings, give every tunable an
  `NCT2CTML_*` environment override, and log `LLM_PLATFORM` and the model at
  startup.

  Done 2026-09-29.
  - The 73 lines of alternative models moved to `doc/llm_backends.md`
    ("Models tried").
  - Every tunable is `_env(...)`: 17 settings, with the old variable names
    kept. Overrides are collected in `config.OVERRIDES`, logged by `main.py`
    and recorded in `run.json`. Paths are deliberately not overridable.
  - `scripts/run_ollama_mapping.sh` now exports the model it pulled.
  - `config.py` went from 278 to 238 lines.

- [x] **11. Split the largest modules as they are touched, not in one rewrite.**
  Broken down in [plan_step11_split_modules.md](plan_step11_split_modules.md);
  all four phases done 2026-09-29.
  - `utils/review_helper.py` (1,448 lines; `analyse` and `main` are the most
    complex functions) -> e.g. `review/cli.py`, `review/checks.py`,
    `review/sheets.py`
  - `utils/ai_helper.py` (1,426) -> one module per prompt, next to its schema
  - `src/clinical_trials_gov.py` (1,136)

  The existing tests make this safe.

- [ ] **12. Type hints at module boundaries.**
  Mapper inputs/outputs, index rows, the platform interface. Then `mypy` or
  `pyright` on `src/` and `utils/` in CI, starting non-strict.

## Phase 3 - Documentation

- [x] **13. Split `CHANGES.md`** (1,769 lines, 100 KB; it is the Apache
  §4(b) notice, a changelog and an experiment log at once).
  - `CHANGES.md`: the fork notice and a short summary per release.
  - `doc/decisions/`: one dated file per measured decision (roadmap 2.8, 2.9,
    2.9b, ...) with question, method, numbers, decision, commit and model.
  - `doc/runs/`: move `doc/run_2026-09-25.md` there as the template.

  Done 2026-09-28. CHANGES.md 2,023 -> 544 lines: the notice, the summary of
  the retargeting and a short summary since. 37 entries moved to
  `doc/changelog.md`, 12 to 11 files in `doc/decisions/`, 8 to
  `doc/runs/` (both run files merged in). Moved verbatim: every line of the
  old file is in one of them.

- [x] **14. Restructure the README.**
  First screen: a 10-line quickstart (Python version, environment, API key,
  pull one trial, map it, build the index) and one diagram
  (pull -> map -> review -> index). Move the review helper, index columns and
  backend details into `doc/` pages and link them.

  Done 2026-09-28. README 519 -> ~220 lines: quickstart, Mermaid diagram,
  usage, workflow and a documentation table. New pages: `doc/review_guide.md`,
  `doc/index_guide.md`, `doc/provenance.md`, `doc/llm_backends.md`,
  `doc/reference_data.md`.

- [x] **15. Cite the fork in `CITATION.cff`.**
  It lists only upstream. Add the Kispi fork as the cited software (own
  repository, version, date) and keep the upstream paper under `references`.
  Add a Zenodo DOI once releases are tagged (step 6).

  Done 2026-09-28 (validated with cffconvert). The fork is the software
  described; the paper stays the preferred citation; upstream is listed
  under `references`. Open: named Kispi authors (only the organisation is
  listed) and a Zenodo DOI.

- [x] **16. Add `CONTRIBUTING.md`.**
  How to run the tests, how to record a measurement (step 13), how to change a
  `ref/` file (step 5), and the rule that a model or prompt change needs
  benchmark numbers first - today that rule lives only in a `config.py`
  comment.

  Done 2026-09-28.

## Suggested order

1. Steps 1-3 - provenance cannot be added retroactively.
2. Steps 7-8 - about a morning, and they protect everything after.
3. Steps 4, 9, 10.
4. Steps 13-16.
5. Step 11 incrementally; step 12 alongside it.
