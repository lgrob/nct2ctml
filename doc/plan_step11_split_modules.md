# Sub-plan: step 11, split the largest modules

Step 11 of [improvement_plan.md](improvement_plan.md), broken into steps that
can each be done, verified and committed separately. Measured at commit
`f91851c` (2026-09-28).

## What is being split, and why

| Module | Lines | Upstream lines left | What is mixed in it |
|---|---|---|---|
| `utils/review_helper.py` | 1,934 | none (Kispi's) | mapping rules the mapper imports; batch fixers over existing output; evidence search; HTML sheets; the accept/exclude gate; the CLI |
| `utils/ai_helper.py` | 1,614 | about 670 | the model transport; the enum cap and candidate checks; about a dozen prompts, each with its text, schema and calling wrapper |
| `src/clinical_trials_gov.py` | 1,301 | about 510 | NCT-specific field mapping, plus the diagnosis, genomic and criteria-splitting logic that `src/ctis.py` reuses by importing the NCT module |

The size alone is not the problem. The problems are:

- **The mapper depends on the review CLI.** `src/trial_map_manager.py`
  imports `gene_status_contradictions`, `diagnoses_only_in_exclusions`,
  `all_lineage_unspecified`, `add_sibling_diagnosis`, `collect`, `B_ALL` and
  `T_ALL` from `utils/review_helper.py`. A change to the curator tool can
  change what the pipeline maps.
- **CTIS mapping imports the ClinicalTrials.gov module.** `src/ctis.py` gets
  shared diagnosis and genomic logic from `src/clinical_trials_gov.py`, so the
  registry-independent code has no home of its own.
- **Tests replace module attributes.** `ai.send_ai_request`,
  `ai.parse_ai_response`, `ai._llm_platform`, `utils.ai_helper.get_age_bounds`,
  `rh.MAPPED_DIR`, `rh.REVIEW_DIR`, `rh.REVIEWED_DIR`, `rh.LOG_FILE`,
  `rh.eligibility_text` and `ctg.map_eligibility_criteria_to_oncotree_term`
  are all replaced this way. Once a function moves, a patch on the old name
  silently stops working. An assignment like `ai.send_ai_request = stub`
  even creates the attribute without complaint. The test then calls the
  **real model**, or writes to the **real `ctml/` directories**. This is the
  main risk of the whole step, and Phase 0 exists to remove it.

## Ground rules for every step

1. **One move per commit, with no behaviour change.** A commit that moves
   code does not also change it. A fix found on the way gets its own commit,
   before or after.
2. **Prove nothing changed.** Each commit passes all of these:
   - the offline suite (598 tests at the start) and `ruff check` /
     `ruff format --check`;
   - the behaviour snapshot from Phase 0: every prompt, schema and CTML
     output for the 56 reviewed trials byte-identical, and the index over
     all mapped trials byte-identical;
   - `python -m bench.conditions_baseline`.
3. **Update patch targets in the same commit** as the move, and never leave
   an old name behind that a test could still assign to.
4. **Keep the commands users type:** `python -m utils.review_helper ...`,
   `python main.py ...`. Where an import path changes, update every importer
   in the same commit, rather than leaving a re-exporting shim whose names
   look patchable but are not.

## Phase 0: safety net (before any move) - small

- [x] **0.1 Behaviour snapshot script.** Add `scripts/behaviour_snapshot.py`.
  It writes one JSON containing the determinism probe's prompt, schema and
  CTML hashes for the 56 reviewed trials, plus the SHA-256 of each index
  table built from the current layers. A `--compare <file>` flag prints the
  differences. The same comparison verified the ruff reformat; this makes
  it one command.
- [x] **0.2 Tests cannot reach a model.** Add an `Offline` LLM platform
  whose `send()` raises "tests must not call a model", and make it the
  platform for the offline suite, so a patch that stops working fails loudly
  instead of calling the API. Live tests (`RUN_LIVE_LLM_TESTS=1`) switch it
  off. To check first: `unittest discover -s tests` imports test modules as
  top-level modules and never loads `tests/__init__.py`, so the guard needs
  either `-t .` in the documented and CI commands, or to be set through the
  environment in CI and in `CONTRIBUTING.md`.
- [x] **0.3 Tests cannot write to real directories.** `test_review_helper`
  reassigns `rh.MAPPED_DIR`/`REVIEW_DIR`/`REVIEWED_DIR`/`LOG_FILE`. Replace
  that with one fixture that points `config` at a temporary tree, and add a
  test asserting no test run touches `ctml/` or `cache/ctml` (a
  modification-time check before and after).

**Done when** the three pieces exist, and a deliberately broken patch (an
assignment to a name that no longer exists) makes a test fail rather than
call the model.

Done 2026-09-29.
- `scripts/behaviour_snapshot.py` also runs `scripts/map_probe.py`: every
  mapped or queued trial (1,180) through `TrialMapManager` under the stub.
  The curated trials alone did not exercise the rules Phase 1 moves:
  disabling the ALL-lineage rule changed nothing among them, but 24 trials
  in the corpus. The snapshot is stable run to run (about 1.5 minutes).
- Offline guard in `tests/support.py`, installed by `tests/__init__.py`; the
  suite runs as `unittest discover -s tests -t .`, and
  `tests/test_offline_guard.py` fails without `-t .`.
- `tests/support.temporary_layers()` and `tests/test_zz_no_writes.py`.
- Found and fixed first: review sheets listed flagged names in set order
  (25 of 175 sheets differed between identical runs), and
  `test_genomic_prompt_variants` left `NCT2CTML_GENOMIC_PROMPT=baseline`
  set for every later test and subprocess.

## Phase 1: `utils/review_helper.py` - no upstream cost, biggest payoff (about a day)

- [ ] **1.1 Separate the rules the mapper uses** into `src/text_rules.py`, imported by both `trial_map_manager` and the review helper:
  `collect`/`_walk`, the gene-alias and term patterns,
  `gene_status_contradictions`, `diagnoses_only_in_exclusions`, the ALL
  lineage rule (`B_ALL`, `T_ALL`, `all_lineage_unspecified`,
  `add_sibling_diagnosis`, and `add_sibling_gene` beside it). After this,
  the mapper imports nothing from the review tool. About 350 lines.
- [ ] **1.2 Package the rest as `utils/review/`:**

  | Module | Contents | About |
  |---|---|---|
  | `paths.py` | `MAPPED_DIR`, `REVIEW_DIR`, `REVIEWED_DIR`, `LOG_FILE`, `SHEET_DIR`, `FLAG_KEYS`, `ADVICE`, `Item`, `_layer_of`, the only place tests redirect | 150 |
  | `evidence.py` | `eligibility_text`, `registry_ages`, `Reference`, `find_mentions`, `near_misses`, `evidence`, `analyse` | 480 |
  | `sheets.py` | `CSS`, `render`, `render_index`, `write_sheets` | 140 |
  | `gate.py` | `problems`, `accept`, `exclude`, the review log, the queue, `audit_sample` | 200 |
  | `maintenance.py` | the batch commands over existing output: `flag_exclusions`, `clear_stale_gene_flags`, `fix_genomic_notation`, `fix_all_lineage`, `resolve_remap_drops`, `flag_gene_status`, `flag_unsupported_genes` | 600 |

  `utils/review_helper.py` keeps only the CLI (`main`), so every documented
  command still works. Do this in five commits, one per module.
- [ ] **1.3 Break up the two most complex functions** (ruff C901):
  `analyse` (complexity 26) into one function per kind of flag, and `main`
  (24) into one handler per subcommand. This is the one part of the phase
  that edits code rather than moving it, so it gets its own commit with the
  snapshot check.

**Done when** `trial_map_manager` imports nothing from `utils/review*`, no
review module exceeds about 600 lines, and the review sheets for the current
queue are identical before and after (`review_helper sheets` into two
directories, then compared). Ignore the generation time on the index page,
which is the only part that changes between runs.

## Phase 2: `src/clinical_trials_gov.py` - registry-independent code gets a home (about half a day)

- [ ] **2.1 Move the logic both registries share to `src/mapping/`:**
  - `diagnosis.py`: `seed_and_map_diagnosis`, `basket_wildcards`,
    `_basket_wildcards`, `map_eligibility_criteria_to_oncotree_term`,
    `map_global_diagnosis_to_oncotree_term`, `diagnosis_text`;
  - `genomic.py`: `map_ctml_match_genomic_criteria`, the normalise and
    enrich steps;
  - `criteria_text.py`: `split_inclusion_exclusion_criteria`,
    `exclusion_heading`.

  `src/ctis.py`, the benchmark and `utils/oncology_scope.py` then import
  from `src/mapping/`, not from the NCT module.
- [ ] **2.2** `src/clinical_trials_gov.py` keeps what reads a
  ClinicalTrials.gov document: general fields, ages from the structured
  fields, biomarker fields, prior treatment, and the `map_nct_to_ctml`
  orchestration. About 550 lines.
- [ ] **2.3 Teach `scripts/merge_upstream.py` about the moves.** A small
  table of which upstream function now lives where, so that a conflict in a
  moved function names the file to carry the change to.

**Done when** `src/ctis.py` does not import `src.clinical_trials_gov`, and
the snapshot is unchanged.

## Phase 3: `utils/ai_helper.py` - one module per prompt (about a day)

- [ ] **3.1 Transport first,** as `utils/llm/transport.py`: the platform
  instance, `send_ai_request` with its call recording, and
  `parse_ai_response`. Every prompt module calls it through the module
  (`transport.send_ai_request(...)`), so one patch target covers all
  prompts. Move the test and probe patches to it in the same commit.
- [ ] **3.2 Schema machinery** as `utils/llm/schema.py`: `max_enum_values`,
  `ENUM_CAP_EVENTS`, `OFF_LIST_EVENTS`, `OFF_LIST_BY_TRIAL`,
  `keep_candidates`, `_one_of`, `prompt_list`, `diagnosis_prompt_list`. The
  counters are module state, so they must live in exactly one module.
- [ ] **3.3 One module per prompt family,** each with its prompt text,
  schema and calling wrapper next to each other:
  `utils/llm/prompts/diagnosis.py` (level 1, Oncotree, child values),
  `biomarkers.py` (HER2/ER/PR, PD-L1, MMR, disease status), `age.py`,
  `arms.py`, `genomic.py` (inclusion and exclusion, the roles and
  `ROLE_DROPS`), and `enrichment.py` (mutation and CNV detail, the
  `has_*_details` checks, `merge_enriched_criteria`). One commit per family.
  Every prompt's text must stay byte-identical, which the snapshot checks.
- [ ] **3.4 Remove `utils/ai_helper.py`** once nothing imports it. About 20
  names are used by `src/`; update those imports in the same commit.

**Done when** no prompt module exceeds about 300 lines, `ai_helper.py` is
gone, and the snapshot is unchanged.

## Decisions to take before starting

1. **Split the upstream files at all?** Phase 1 costs nothing upstream.
   Phases 2 and 3 mean that an upstream fix to a moved function has to be
   carried over by hand. Upstream has changed these two files in 45 commits,
   17 of them in 2026, the latest in July; 2.3 makes that easier but not automatic. Alternatives:
   do Phase 1 and 3.1 only (the transport seam removes the monkeypatch risk);
   or do Phases 2 and 3 only after one more upstream merge. Recommended:
   Phases 0 and 1 now, then decide on 2 and 3 with that experience.
2. **Names:** `src/text_rules.py` (chosen 2026-09-29) vs `src/mapping/rules.py`, and `utils/llm/` vs
   `src/llm/`. They can be settled at 1.1; changing them later is another
   round of moves.
3. **The test command:** switch to `unittest discover -s tests -t .` if 0.2
   needs `tests/__init__.py` loaded. That changes CONTRIBUTING.md and
   `tests.yml`.

## Order and size

| Phase | Commits | Effort | Upstream cost |
|---|---|---|---|
| 0 safety net | 3 | a few hours | none |
| 1 review_helper | about 8 | about a day | none |
| 2 clinical_trials_gov | 3 | about half a day | moved functions need porting |
| 3 ai_helper | about 9 | about a day | moved functions need porting |

Each phase leaves the repository working and can be the last one done.
