# Engineering log

What changed in this fork after the initial retargeting, newest first. Moved from CHANGES.md on 2026-09-28 (improvement plan step 13); the entries are unchanged. Measured decisions are in [decisions/](decisions/), mapping runs and queue reviews in [runs/](runs/).

## Disease status no longer published (2026-10-02)

`config.PUBLISH_DISEASE_STATUS` (default False) gates the disease-status model
call in `clinical_trials_gov.map_nct_to_ctml`. Off, the call is skipped and no
`disease_status` criterion is written. MatchMiner can satisfy the criterion
only from a disease status the patient records do not reliably carry, and the
model's reading was wrong in 7 of the 60 audited trials
([decision](decisions/2026-10-02-no-disease-status.md)). Replayed: 802 of
1,133 trials lose the criterion; routing and benchmark scores are unchanged.
The setting is read from the repository's `config.py`. In
`clinical_trials_gov`, `config` is `src.trial_config`, so its existing
`getattr(config, "DIAGNOSIS_INPUT", ...)` always sees "legacy"; that read
only decides the inclusion_only title, so the current default is unaffected.
3 tests.

## Index releases cover all three layers (2026-10-02)

`utils/release_index.py create` builds from all three layers by default, the
user's choice for the first release. The index inputs outside git (the
mapped and needs-review CTML, `ctml/out-of-scope.tsv`) are packed into the
archive under `<tag>/inputs/` with their SHA-256 in `release.json`.
`verify` checks them, and `--rebuild` restores them into the tagged commit's
worktree before requiring byte-identical tables. `--note` records a caveat (the
audit) in `release.json` and the tag; `--layers reviewed` keeps the
curated-only release. 5 tests.

## A diagnosis floor from the inclusion text, on by default (2026-10-02)

`ref/diagnosis_groups.tsv` (110 terms, drafted by Claude, revised by the user)
names how eligibility texts state a population - glioma and sarcoma groups,
pre-2021 WHO names, leukaemia and lymphoma groups, baskets - and
`reference_validation.diagnoses_from_text` adds the matching Oncotree terms to
the model's diagnosis answer when `DIAGNOSIS_TEXT_FLOOR` is on (the default
since this entry; mapped files record the setting in `_provenance`). It reads the title, conditions and inclusion criteria, runs after
the model call so prompts and replays are unchanged, and never removes a term.
Guards: per-row lineage and subtype guards, two-sided where a guard contains
"§" (the table's TODO 2), a global guard against assessment criteria and stated
expertise, bracketed abbreviations inheriting their term, and a lineage veto
for unqualified ALL/LBL/NHL. Measured by replay of the gpt-oss corpus: 9 of the
audit's 11 missing-diagnosis failures closed, benchmark recall unchanged, NCT
population precision 0.810 -> 0.681, CTIS unchanged
([decision](decisions/2026-10-02-diagnosis-text-floor.md), adopted). 19 tests.

## The cluster job's map-all maps every trial (2026-10-01)

`scripts/run_ollama_mapping.sh map-all` ran `main.py map --all`, which maps
only the NCT trials updated in the last `MAPPING_CUTOFF_DAYS` (1 day, the
nightly incremental setting). The first gpt-oss corpus run (job of
2026-10-01, run `20261001T125000Z-0bd723`) therefore mapped 277 trials, the
recently updated NCT ones and the cached CTIS ones, not the corpus. map-all
now passes `--cutoff-days 36500`; `CUTOFF_DAYS=N` restores an incremental
run and `SOURCE=nct|ctis` maps one registry.

## gpt-oss:120b on Ollama is the default backend; runs record the served weights (2026-10-01)

`config.py` now defaults to `LLM_PLATFORM = "Ollama"`, `LLM_AI_MODEL =
"gpt-oss:120b"`, `OLLAMA_THINK = "low"` and `OLLAMA_NUM_PREDICT = 16384`, the
settings of the benchmarked run, for reproducibility: the weights can be kept
and rerun, a hosted snapshot cannot
([decision](decisions/2026-10-01-gpt-oss-backend.md)). Haiku stays available
through `NCT2CTML_LLM_PLATFORM=Anthropic`. The corpus in `cache/ctml` and the
index are still Haiku's until remapped.

A tag such as `gpt-oss:120b` can be re-published with new weights, so
`OllamaPlatform.model_digest` asks the server for the digest it holds under
the tag. `provenance.start_run` records it in `run.json` and every file's
`_provenance`, and refuses to start when `OLLAMA_MODEL_DIGESTS` pins another
digest for the model or the digest cannot be read. gpt-oss:120b is pinned to
the benchmarked weights, `a951a23b…ecd9`; a model not in the table is
recorded but not checked, and `NCT2CTML_OLLAMA_MODEL_DIGEST` overrides the
pin for one run (`off` skips it). The offline test guard reports the pinned
digest as served instead of asking a server. 7 tests.

## A diagnosis call that answers with its candidate list goes to review (2026-10-01)

The other shared failure in
[runs/2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md](runs/2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md):
NCT04732065 and NCT06528691 each came back with exactly 126 diagnoses from
both models, against 4 and 1 curated.

**126 is the size of the list, not a judgement.**
`mapping/diagnosis.map_eligibility_criteria_to_oncotree_term` builds the
stage-2 candidates from `onct.get_all_oncotree_data()`, which maps each
level-1 node to its whole subtree rather than its level-2 children. For
`CNS/Brain` that is exactly 126 terms - the subtree is 127 nodes including
the root and the root itself is not in the list - so both models returned
their entire candidate list verbatim. `keep_candidates` drops off-list
answers, so an answer can never exceed the list, and exactly 126 can only
mean all of it. Nothing expanded anything on the output side; the broad
category was in the prompt. It shows on brain trials because `CNS/Brain` is
the largest branch in Oncotree (126, against 120 Lymphoid, 106 Myeloid, 54
Soft Tissue) and the only one at or above 126, still under the Ollama enum
cap of 400, so the cap is not involved. The same failure, milder: Qwen on
NCT04775485 (121 of 126) and both models on NCT04897321 (73 and 78 of a
148-term list over seven branches).

**`keep_candidates` was blind to it by construction.** It checks membership,
and every answer was a member; nothing looked at how many there were. So the
trial was published with 126 diagnoses, no flag and no review routing, and
it matched every brain-tumour patient in the database.
`schema._over_generated` now reads a call that answers with at least
`config.DIAGNOSIS_OVER_GENERATION_SHARE` (0.4) of a candidate list of at
least `DIAGNOSIS_OVER_GENERATION_MIN_LIST` (20) terms as the list back rather
than an answer, records the worst such call of the trial in
`OVER_GENERATION_BY_TRIAL`, and `TrialMapManager._record_over_generated_diagnoses`
writes it to the CTML as `diagnosis_over_generated`, which routes the trial
to review. The answer is left as the model returned it: a curator decides the
population, with the trial's own `conditionsModule` terms as the floor. The
list floor is what keeps the rule off short branches - Peritoneum offers 2
terms and Prostate 5, where one right answer is already half the list.

Measured over the 1,236 mapped trials of the 2026-09-28 full run, the 1,149
of them carrying a real Oncotree diagnosis: the share of its own candidate
list a mapping takes has median 0.032 and p99 0.434, and the 52 curated keys
never exceed 0.222 (2023-505575-69-01, 5 of 23). The rule fires on **7 of the
1,149 (0.6%), every one in the published layer and none a curated key**, and
on all four of the benchmark over-generators including both NCT04897321
replicates. The candidate lists in that measurement are reconstructed from
the branches each output's own diagnoses fall in, so the denominators are
lower bounds and the shares upper bounds - in the pipeline the real list is
in hand, and the rule can only fire less often than measured.

Returning a whole branch is never the right encoding in any case: the
matchengine expands a parent to all its descendants, so the 126 leaves and
the single node `CNS/Brain` reach the same patients, and a genuinely pan-CNS
trial is one node or a `_SOLID_` wildcard. Not done: falling back to the
conditions seed instead of keeping the model's list, which would change
published output and needs its own measurement.

## A genomic answer dropped to nothing goes to review (2026-10-01)

Found while reading the seven trials that scored 0.00 on genes for both
local models in [runs/2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md](runs/2026-09-30-ollama-qwen3.6-gpt-oss-benchmark.md).
Five of the seven turned out not to be model errors at all; three fixes come
from that reading, and the rest is written up in the run record.

**A dropped genomic criterion could empty the match tree silently.** Each
drop in `convert_to_ctml_genomic_schema` is defended on its own as narrowing
one criterion among several - `filter_genomic_criteria`'s docstring makes
that argument explicitly. The argument inverts when the drop takes the last
one: the function returns `{}`, `combine_clinical_and_genomic_ctml` falls
through to "using only clinical CTML", and the trial is published matching
every patient with the diagnosis, with the alteration it requires asked of
nobody. That is the failure the no-diagnosis rule already guards one level
up, reached by another route, and it left no trace beyond a `logger.warning`:
no flag, no review routing, nothing in the index. Replaying answer shapes on
NCT07440290 (key `BRAF`, scan list exactly `['BRAF']`) shows four that empty
the tree and route nowhere: the alteration written into `hugo_symbol`
(`BRAF V600E`, `BRAF (V600E)`), a fusion written as a pair (`NTRK1-ETV6`),
and no `variant_category` at all. `match_criteria_mapper.GENOMIC_EMPTIED` now
records the symbols the model named when nothing survives,
`TrialMapManager._record_genomic_emptied` writes them to the CTML as
`genomic_emptied`, and `_destination_for` sends the trial to review - the
same hand-off as `gene_role_dropped`, and the same routing as
`genomic_contradiction`. A trial whose model answer was genuinely empty is
untouched: that is not the same thing as one whose criteria were dropped.

**`KeyError: 'variant_category'` lost whole trials.** The guard above the
inclusion loop asks only that `hugo_symbol` and `variant_category` each
appear *somewhere* in the model's list, then the loop indexed
`alteration["genomic"]["variant_category"]` directly. A list where some items
carry the key and others do not therefore raised, and the callers catch that
as a mapping failure - so one malformed item cost the trial, not just the
item. The loop skips and logs the item instead; if that empties the block,
`genomic_emptied` picks it up.

**The cohort-negation cue is anchored to the gene.** Case 2 of
`resolve_contradictory_genes` drops both sides of a contradictory gene when
the inclusion text negates it, which is right for the SIOPEN design the
docstring cites. The cue was tested against the whole inclusion text, so the
branch fired on prose with nothing to do with the gene: "without" occurs
somewhere in the inclusion text of 18 of the 50 benchmark trials, any cue in
25 of 50. NCT05580562, the trial the same docstring names as the case-1
example, was taking case 2 because "lack of" appears in an unrelated
criterion. `_cohort_negation_near` now requires the cue in the same bullet,
line or sentence as the gene. Enumerated over all 189 (trial, gene) pairs the
scan finds in the 50 benchmark trials, 106 pairs on 15 trials change branch,
51 of them on a gene in the answer key, and every change is cohort to
artefact - the stated inclusion is kept instead of both sides going. Nothing
moves the other way, so the change can only keep a criterion the trial
states; the cost is that a cohort split expressed away from the gene's own
sentence now keeps the inclusion and loses the without-the-alteration cohort.
NCT04221035's MYCN, negated in the sentence that names it, still takes case 2.

## The Anthropic backend works again on anthropic 1.4.0; gpt-oss and Qwen3.6 on the cluster (2026-09-30)

**Every Anthropic call had failed since the environment was pinned**
(plan step 4, `23050fe`): `anthropic` 1.x removed `temperature` from
`messages.create()`, so each request raised `TypeError` before it was sent.
The first corpus run afterwards (`runs/20260930T115133Z-636913`) failed all
1,141 calls; nothing was written or overwritten. The tests passed because they
mock the client, which accepts any keyword. Temperature now goes through
`extra_body` (Haiku 4.5 still accepts it, and the documented measurements were
made at 0), and a new test checks every key the platform builds against the
installed SDK's signature.

**`OLLAMA_THINK`** (`NCT2CTML_OLLAMA_THINK`: false/true or low/medium/high)
sets Ollama's `think` field, which was fixed at false. gpt-oss cannot turn
reasoning off, so it needs a level; the level is recorded in each run's
provenance. `scripts/run_ollama_mapping.sh` refuses gpt-oss with thinking off,
and its benchmark mode now writes `bench/output-<model>[-rep<N>]/` with the
report inside, so runs of different models no longer overwrite each other or
the tracked `bench/report.json`. Its comment, which said CTIS keys were not
scored, is corrected. It also runs under Singularity where Apptainer is
missing, and forces OLLAMA_HOST=127.0.0.1 inside the container: the ollama
image sets 0.0.0.0 itself, which sends client calls to the site proxy.

**The benchmark kept losing the trials it routed to review.** A trial the
mapper flags goes to `CTML_REVIEW_PATH`, and in a benchmark run that was the
curators' `ctml/needs-review`. The scorer read only `--out`, so the trial
counted as "MISSING OUTPUT" and left the means: the hardest trials dropped out
of the score, a different set per model. The benchmark now points the queue at
`<out>/needs-review` for the run (and restores it), scores those trials, marks
them `to_review` in the report and lists them in the summary. The committed
Haiku report scored all 50, so it was not affected; the first qwen3.6:27b run
(job 6752539) was.

## A review interface, and the diagnosis-seed rules (2026-09-30)

**`python -m utils.review.app`** serves the review sheets at 127.0.0.1:8765 with
an editor and the decision on the same page. Save writes the file, keeps the
previous version as `.prev` and re-runs the gate, so the page shows what
`accept` would refuse; Accept and Exclude call `gate.accept` / `gate.exclude`
unchanged, so the log and the SHA-256 are written as before. Standard library
only (`http.server`), so `requirements.lock` is untouched. The static sheets and
the CLI are unchanged. Documented in [review_guide.md](review_guide.md);
16 tests, none of which bind a socket.

**Diagnosis-seed rules** from the 3.4 audit, measured over all 1,146 indexed
trials before adoption
([decision](decisions/2026-09-30-conditions-seed-rules.md)):

- `ref/diagnosis_abbrev_exclusions.tsv` (mirroring the gene side) stops the
  conditions seed resolving an ambiguous abbreviation: `GCT` had become Granular
  Cell Tumor on a germ cell tumour trial, `RAS` Radiation-Associated Sarcoma on a
  colorectal one. Two rows, curator-extensible; enforced in
  `reference_validation.diagnoses_from_conditions`.
- `text_rules.diagnosis_seed_suspect` flags two scope errors and removes nothing:
  a basket resting on the condition "Oncology" (a specialty, not a population —
  2 trials, both wrong), and a B-lineage criterion on a trial whose text names
  only T-lineage disease (8 trials; Oncotree has no lineage-free ALL node, so
  unqualified ALL maps to B-ALL). The flag routes to review;
  `review_helper flag-diagnosis-seed [--apply]` applies it to existing CTML —
  10 trials, all currently published, not yet applied.
- Two wider variants were measured and **not** adopted: the same basket rule on
  the word "cancer" (17 trials, 10 of them legitimate category headers) and
  automatic detection of abbreviation collisions (text corroboration flags 18 of
  40, almost all correct expansions; lineage consistency flags 1, a false
  positive). Widening the unqualified-ALL rule was also rejected: of 141 trials
  where it declines to fire, every sampled one declines correctly.

One correction to the audit note: NCT07262489's Hepatocellular Carcinoma comes
from the model reading an incidental mention, not from the conditions seed, so
the seed rules reach 2 of its diagnosis-scope causes rather than 3.

## The two age defects from the 3.4 audit (2026-09-29)

Both found by the audit of the second full run
([runs/2026-09-29-3.4-audit.md](runs/2026-09-29-3.4-audit.md)). Deterministic,
no model calls, and the corpus was corrected in place rather than re-mapped.

- **Defect A: the upper age bound was one unit too wide.** The
  ClinicalTrials.gov path added a completed unit to `maximumAge` and kept
  `<=`, so a 40-year maximum was published as `<=41`. MatchMiner treats `<`
  and `<=` identically - `map_age_numerical` said so in a comment - but the
  flat index reads the operator literally, so `age_max_inclusive` was `1` and
  a consumer joining on whole years admitted an extra year of patients. 496
  of the 765 indexed trials with an upper bound were affected; the prose path
  (`age_bounds.prose_bounds`) already emitted `<N+1`, which is why the
  prose-corrected CTGOV trials and every CTIS trial were right.
  `map_age_numerical` now passes `<`, and
  `review_helper fix-age-operator [--apply]` rewrites existing CTML by text
  (465 bounds in 465 trials). After rebuilding the index,
  `age_max_inclusive = 1` fell from 496 rows to 31: 28 in `ctml/reviewed`,
  which the pass never touches because each accepted file's SHA-256 is in
  `ctml/review_log.tsv`, and 3 mapped or queued files with curator comments.
  **The 28 reviewed trials are what the first release builds from, so they
  need a curator's decision before 3.3.**
- **Defect B: a sponsor's units error published as a neonatal window.**
  `text_rules.age_units_implausible` reports a trial whose structured age
  fields are in days, weeks or months while the inclusion text states the
  same two numbers in years. The mapper writes `age_units_implausible`, which
  routes the trial to review (`_flag_age_units`, ClinicalTrials.gov only:
  CTIS publishes no structured age), and leaves the bounds as the registry
  states them - which field the sponsor meant is a curator's call.
  `review_helper flag-age-units [--apply]` applies it to existing CTML. The
  numbers have to match, so a real neonatal study ("18 to 70 days") is not
  reported. Four trials, all now in the review queue: NCT06342336 and
  NCT07106892 (18-75 Days against 18-75 years), NCT06776952 (18-70 Days
  against "Aged 18-70 years (inclusive)") and NCT06375161 (18-70 **Weeks**,
  published as 0.34-1.36 years), which the audit's sample had missed. All
  four are tagged `stdAges: CHILD` by the registry, which is why adult trials
  were in a paediatric corpus at all.

Index after both passes and a rebuild: 1,146 trials, 913 mapped (was 916),
177 needs review (was 174), 56 reviewed; diagnosis and genomic tables
unchanged. 645 offline tests (25 new in `tests/test_age_units.py`).

## Improvement plan removed (2026-09-29)

All 16 steps are done. `doc/improvement_plan.md` is removed; it is in git
history at `2a3f65e`. Where this log says "step N of doc/improvement_plan.md",
that is the file meant. Its open items moved to
[open_issues.md](open_issues.md), "Follow-ups from the improvement plan".
`doc/plan_step11_split_modules.md`, the sub-plan for step 11, is removed too
(in git history at `35c0ad8`); what the refactor found is in the step 11
entries below.

## Type checking with mypy (improvement plan step 12, 2026-09-29)

- **mypy, non-strict**, on `main.py`, `config.py`, `src/`, `utils/`, `bench/`
  and `scripts/`. The configuration is in `pyproject.toml`, and
  `explicit_package_bases` is needed because two modules are named
  `biomarkers`. mypy and the PyYAML and requests stubs are pinned in
  `requirements-dev.txt`, and CI has a new `types` job, checked in a fresh
  3.12 environment from the lock.
- **The 43 findings on the existing code** were annotations that did not
  match what the code does: empty containers, `None` defaults, a parameter
  that takes a list or a dict, an optional client. None changed behaviour.
  Three small code changes came with them:
  - `ArmCriteriaText.get_combined_eligibility_text` became
    `match_criteria_mapper.combined_eligibility_text(arm)`, because a
    TypedDict cannot carry methods.
  - `read_from_file` and `read_from_file_path` raise for a format other than
    json, instead of returning `None` to a caller that indexed it.
  - `map_gender` returns `""` rather than `{}` for an unmapped sex; output is
    identical.
- **Boundaries annotated:** `utils.llm.transport`, `src/mapping/`, and the
  public functions of `src/text_rules.py`. The index rows are TypedDicts
  (`TrialRow`, `DiagnosisRow`, `GenomicRow`), and the column lists are
  derived from them; `tests/test_index_rows.py` checks that a built index
  has exactly those columns. On a scratch file, mypy flagged a wrong
  argument type, a wrong schema type, a set method called on the returned
  list, and an index row missing its columns.
- **Next level:** `check_untyped_defs`, which reports 136 findings today (43
  in `utils/provenance.py`).

## Registry-shared mapping and the model code split out (step 11, phases 2-3, 2026-09-29)

- **`src/mapping/`** (new) holds what both registries share: the diagnosis
  path (`seed_and_map_diagnosis`, the two-stage Oncotree mapping, baskets,
  `diagnosis_text`), genomic criteria, and biomarker status. `src/ctis.py`
  no longer imports the ClinicalTrials.gov module for them.
  `clinical_trials_gov.py` went from 1,301 to 811 lines; everything left
  reads the NCT document.
- **`utils/llm/`** (new) replaces `utils/ai_helper.py`, now removed:
  - `transport.py` (platform, `send_ai_request` with recording,
    `parse_ai_response`);
  - `schema.py` (enum cap, candidate checks, prompt list order);
  - `prompts/` with one module per family: diagnosis, biomarkers, age,
    arms, genomic, enrichment.

  Tests and probes stub the model in one place, `utils.llm.transport`.
- **`scripts/merge_upstream.py`** names, for each function upstream changed
  in a conflicted file, where it lives in this fork now.
- **How it was checked.** Every move was verbatim and snapshot-checked. At
  the end, the whole of phases 2 and 3 was compared with `c00f5a3` under a
  stub model that names a gene: identical output for all 1,180 trials and
  identical prompts for the 57 curated ones.
- **Found and fixed:**
  - Genes kept out of the match tree were not recorded after the genomic
    prompt move (`e886db1`; no map run used it). The mapper tested
    `hasattr(ai_helper, "ROLE_DROPS")`, which the move tool could not see,
    and the old stub model never produced a gene, so the snapshot could
    not see it either. The stub now answers TP53, and a test covers the
    hook.
  - A prompt-variant test leaked its stub model into every later test once
    a reload no longer undid it; the offline guard test caught it.
  - The probes' "refuse to send" platform pointed at the old module and
    would have guarded nothing.
  - `doc/open_issues.md` still listed the arm prompt as schema-less; it has
    a schema.

## config.py: overridable settings, catalogue moved out (improvement plan step 10, 2026-09-29)

- **Overrides.** Every tunable setting can be set as `NCT2CTML_<NAME>`: 17 of
  them, through one helper, `_env`. `NCT2CTML_LLM_PLATFORM`,
  `NCT2CTML_DIAGNOSIS_INPUT`, `NCT2CTML_GENOMIC_PROMPT` and
  `NCT2CTML_REPLAY_FILE` work as before. Values are typed: ints, floats,
  booleans, and `none` for an optional value. A bad value stops at import
  with the variable named. Paths stay fixed on purpose: the reference files
  are checked against `ref/SOURCES.tsv`.
- **Overrides are never invisible.** `config.OVERRIDES` lists them, `main.py`
  logs the settings and, as a warning, the overrides at startup, and every
  run writes them to `run.json` (`config_overrides`).
- **Model catalogue moved.** The 73 commented-out alternative models and
  their notes (GPU sizes, benchmark scores, why each was not adopted) moved
  verbatim to `doc/llm_backends.md`, "Models tried". `config.py` went from
  278 to 238 lines.
- **Fixed:** `scripts/run_ollama_mapping.sh` pulled and warmed up `$MODEL`,
  but the mapping read its model from `config.py`, so
  `MODEL=... sbatch scripts/run_ollama_mapping.sh` could map with a different
  model than it loaded. It now exports `NCT2CTML_LLM_AI_MODEL=$MODEL`.
- `tests/test_config.py` is new: 6 tests, each in a fresh interpreter.

## Review helper split; mapper no longer imports it (step 11, phase 1, 2026-09-29)

- **`src/text_rules.py` (new, 467 lines).** The rules the mapper applies
  after the model, moved verbatim from `utils/review_helper.py`:
  exclusion-only diagnoses, gene-status contradictions, ALL named without a
  lineage, and the sibling helpers, together with `Reference` and
  `find_mentions`. `trial_map_manager` imports it instead of the review
  tool.
- **`utils/review/` (new).**
  - `common.py`: paths, flag keys, advice and `Item`. The one place tests
    redirect the layers.
  - `evidence.py`: a trial's text and `analyse`.
  - `sheets.py`: the HTML sheets.
  - `gate.py`: problems, accept, exclude, the queue and the audit sample.
  - `maintenance.py`: the batch commands.

  `python -m utils.review_helper` is unchanged for users. The file is now the
  CLI only, about 290 lines where it was 1,934.
- **Two complex functions broken up.** `analyse` (C901 complexity 26) is
  split into one helper per kind of sheet item, in the same order, and
  `main` (24) into a handler per subcommand.
- **How it was checked.** Every step was moved verbatim by an AST tool that
  rewrote references to `module.name`, so patches keep taking effect.
  `scripts/behaviour_snapshot.py` was unchanged after each of the 8
  commits: prompts, 1,180 trials through `TrialMapManager`, the index, the
  review queue, the batch dry runs, `check` and all 175 sheets.

## Refactoring safety net (step 11, phase 0, 2026-09-29)

- **`scripts/behaviour_snapshot.py`** captures everything a move must not
  change, and `--compare` checks it:
  - prompts, schemas and CTML of the curated trials (determinism probe);
  - every mapped or queued trial through `TrialMapManager` under a stub
    model (`scripts/map_probe.py`, 1,180 trials);
  - the index tables;
  - the review helper's queue, the dry runs of its batch commands, `check`,
    and the review sheets.

  It is stable run to run, fails if it changed any file it only reads, and
  noticed a disabled ALL-lineage rule (24 trials). The stub model is now
  shared (`scripts/stub_model.py`), and both probes replace the platform
  with one that refuses to send.
- **The offline suite cannot call a model.** `tests/support.py` wraps the
  platform so that sending raises. `tests/__init__.py` installs the wrapper,
  so the suite runs as `unittest discover -s tests -t .` (README,
  CONTRIBUTING and CI updated), and `tests/test_offline_guard.py` fails when
  it is missing.
- **No test may change `ctml/`, `cache/ctml`, `ref/`, `index/`, `runs/` or
  `review_sheets/`.** `tests/test_zz_no_writes.py` checks this, and
  `tests/support.temporary_layers()` redirects the review layers for tests
  that write.
- **Fixed:** `test_genomic_prompt_variants` restored the environment
  wrongly. Its teardown set `NCT2CTML_GENOMIC_PROMPT=baseline` again, so
  every later test, and every subprocess it started, ran with the baseline
  genomic prompt instead of the default `roles`. It also reinstalls the
  guard after reloading `ai_helper`.

## Documentation reorganised (improvement plan 13-16, 2026-09-28)

- **CHANGES.md split** (2,023 -> 544 lines). It keeps the Apache notice, the
  summary of the retargeting and a short summary since. The dated entries
  moved verbatim here; the measured decisions to `doc/decisions/` (11 files,
  with an index and a template); the runs and review audits to
  `doc/runs/` (8 files, the two `doc/run_*.md` merged in). A check confirmed
  every line of the old file is in one of the new ones. References in
  `config.py`, `utils/llm_platforms.py`, `doc/open_issues.md` and
  `doc/roadmap.md` now point at the new files.
- **README** (519 -> about 220 lines): a quickstart, a Mermaid diagram of the
  pipeline, usage, workflow and a table of the documentation. The review
  helper, index, provenance, backend and reference-data sections moved to
  their own `doc/` pages; tests and linting moved to CONTRIBUTING.md. The
  workflow now names `review_helper accept`, and the review-queue reasons are
  given as examples, not as the full list. The Mermaid diagram was not
  rendered here; check it on GitHub.
- **CITATION.cff** describes the fork (version 0.1.0, this repository) and
  keeps the upstream paper as the preferred citation, with upstream's
  software under `references`. It validates against CFF 1.2.0 with
  cffconvert. Only the organisation is listed for Kispi.
- **CONTRIBUTING.md** (new): tests, linting, the rule for changing a prompt,
  model or mapping rule (measure both arms, write a decision, then change the
  default), reference-data changes, releases, upstream merges, and where each
  kind of change is recorded.
- Two broken links fixed: an anchor into the mapping guide that no longer
  existed, and a link to a deleted file.
- `.gitignore` had `runs/` for the model-call records, which also matched
  `doc/runs/` and would have kept every run record out of git. It is now
  `/runs/`, the top-level directory only.

## Index releases (2026-09-28)

Step 6 of `doc/improvement_plan.md`. Before this, `index/` was overwritten by
every sync, not in git, and by default built partly from unreviewed trials.
An index behind a patient report was therefore gone by the next run, and
could not be rebuilt, because its inputs in `cache/` were not kept.

- **`utils/release_index.py` (new).**
  - **`create`** refuses unless the tree is clean and `ref/` verifies. It
    builds from `ctml/reviewed` with `--strict` and writes `release.json`
    (commit, and the SHA-256 of every reviewed CTML file, reference file and
    output). It packs a reproducible `releases/<tag>.tar.gz` with a
    `.sha256` file, and tags HEAD with the archive's hash in the message.
  - **`verify [--rebuild]`** checks the archive against all three records;
    with `--rebuild`, the outputs rebuilt from the tagged commit must be
    byte-identical.
  - Nothing is pushed or uploaded automatically.
- **Checked in a scratch clone:**
  - a release of the 56 reviewed trials rebuilt byte-identical;
  - refused: an uncommitted edit, an untracked reviewed file, a committed but
    unpinned change to `ref/genes.txt`;
  - a same-day second release became `.2`;
  - caught: a moved tag, an edited table, an archive swapped under its
    `.sha256`, and a forgery that rewrote the archive, `.sha256` and
    `release.json` together. The last is caught by the tag.
- **Tests:** `tests/test_release_index.py` (7 tests) runs the whole cycle in
  a temporary clone. `tests.yml` now checks out the full history.
- **Found on the way:** the index build also reads the untracked
  `ctml/out-of-scope.tsv`, but that file never drops a reviewed trial, so a
  reviewed-only release does not depend on it. The rebuild check confirms
  it.

## Tests and a benchmark regression check in CI (2026-09-28)

This completes step 8 of `doc/improvement_plan.md`, apart from CTIS.

- **`tests/fixtures/registry/nct/` (new, 888 KB):** frozen records of the 50
  curated NCT trials, plus `NCT06776952`, which an age test reads.
  ClinicalTrials.gov content is public domain.
- **CTIS records are not included.** EMA's legal notice allows reproduction
  but excludes third-party content, and CTIS records are submitted by
  sponsors. The 6 curated CTIS trials, and the 4 tests that need them, stay
  out of CI until that is settled.
- **`bench/conditions_baseline.py` (new)** runs the model-free diagnosis
  path on the fixtures and compares each trial's diagnoses, and the mean
  scores, with `bench/baseline_conditions_nct.json`.
  - The baseline is identical under three hash seeds and matches
    `benchmark_map --conditions-only` on the live cache: dx F1 0.739, pop P
    0.920, pop R 0.784.
  - Removing one curated synonym row fails it and names the five ALL trials
    that lose B-ALL.
- **`.github/workflows/tests.yml` (new)** runs the suite on 3.12 and 3.13
  from the lock, with the fixtures copied into `cache/nct`, then the
  baseline check. Simulated locally in a copy without `cache/`, with a fresh
  3.12 venv: 591 tests, 7 skipped. On GitHub: 2 live-LLM tests and 4 CTIS
  tests; the 7th skipped only because the copy had no `.git`.
- **`requirements-dev.txt`** pins `jsonschema==4.26.0`, so the 7 schema
  tests that used to skip now run in CI.

## Reference data accounted for and pinned (2026-09-28)

Step 5 of `doc/improvement_plan.md`, and the reference check of step 8.

- **`ref/SOURCES.tsv` (new)** lists every file in `ref/` with its kind,
  source, version, date retrieved and notes.
  - **Pinned:** the seven files from outside are pinned by SHA-256. Fetched:
    Oncotree. Built: MANE ×2 and NCBI gene synonyms ×2. Supplied: Kispi's
    panel and its HGNC-resolved form.
  - **Not pinned:** the seven curated files, because git records every edit
    to them, and `review_helper exclude` writes one of them.
  - **Dates:** files placed before this list existed carry the date of the
    commit that added them.
- **`utils/verify_refs.py` (new, standard library only)**:
  - The default mode fails on an unlisted file, a missing file, or a pinned
    file whose hash changed.
  - `--update` re-pins after a deliberate rebuild.
  - `--online` compares the Oncotree tree with the API.
  - `--fetch-oncotree` is the fetch step `ref/oncotree_file.txt` never had.
  - `.github/workflows/reference-data.yml` runs it offline on every push and
    online weekly. `tests/test_reference_sources.py` has 15 tests.
- **Found on the way:**
  - **Oncotree edits a version in place.** For `oncotree_2025_10_03`, the
    API now serves a different layout and row order, and two extra
    cross-reference codes for SRCCR, compared with the file upstream placed
    on 2026-06-15. The tree itself is identical. Hence the pinned hash and
    the tree-only online check.
  - **Parents are keyed by display name.** `get_lineage` does this, and nine
    germ-cell and sex-cord names have two parents. Row order therefore picks
    the parent. This affects no output today, because `parent` is only read
    for ", NOS" names; recorded in `doc/open_issues.md`.

## Dead and misplaced files (2026-09-28)

Step 9 of `doc/improvement_plan.md`.

- **Removed.**
  - `rag/`: two upstream notebooks that nothing references.
  - `yaml/.DS_Store`: `.DS_Store` is now gitignored. The `yaml/` directory
    also made ruff sort PyYAML's `import yaml` as a local package; with it
    gone, those imports moved to the third-party group.
  - `tests/test_ctml_conversion.py`: a loop running `main.py map` on 24
    trials, with no assertions. unittest never collected it, but pytest
    would have, calling the live API and overwriting `cache/ctml`.
- **Kept, moved:** `bulk_convert_yaml_to_json.py` is now
  `python main.py promote` (`utils/promote.py`). `open_issues.md` and roadmap
  6.7 had it down as possibly dead, but `matchminer-admin` loads the
  `ctml/json` it writes into MatchMiner. A dry run no longer creates
  `ctml/json`.
- **Moved:** `tests/determinism_probe.py` is now in `scripts/`; it is a
  helper that `test_prompt_determinism` runs, not a test.
- The debug `print()` calls in the tests are gone. 573 tests pass.

## Lint and format with ruff, checked on GitHub (2026-09-28)

Step 7 of `doc/improvement_plan.md`, plus the lint part of step 8. ruff
(0.16.5, pinned in `requirements-dev.txt`) replaces a Black + flake8
toolchain. Rules in `pyproject.toml`: pyflakes, pycodestyle, bugbear, import
order and pyupgrade, at line length 100. Three commits:

1. **Findings that needed a person** (`45c08b6`).
   - `config.py` and `src/clinical_trials_gov.py` had an import above the
     licence notice, so their docstrings were not module docstrings.
   - `test_prompt_determinism` passed a set literal containing "a" twice, so
     it never actually tested de-duplication.
   - `zip(strict=True)` where the two sides must line up.
   - `src/get_all_intervention_types.py` deleted (step 9).
2. **The mechanical reformat** (`04c8de4`, 79 files, listed in
   `.git-blame-ignore-revs`): `ruff check --fix`, then `ruff format`.
   Behaviour checked unchanged:
   - every prompt, schema and CTML output of the 56 reviewed trials is
     byte-identical (484 model calls, `tests/determinism_probe.py`)
   - the flat index over 1,146 trials is byte-identical
   - 570 tests pass

   Trailing whitespace inside the prompt strings is left alone (`W291` and
   `W293` are ignored), because removing it would change what the model is
   asked.
3. **CI and tooling.**
   - `.github/workflows/lint.yml` runs `ruff check` and
     `ruff format --check` on push and pull request.
   - `.pre-commit-config.yaml` runs the same checks locally.
   - `tests/test_environment.py` checks that CI, pre-commit and
     `requirements-dev.txt` name one ruff version.
   - `scripts/merge_upstream.py` merges upstream without the conflicts the
     reformat would cause. Each file is merged three ways, with both the
     merge base and upstream's version formatted. On a simulated upstream
     update, a plain merge conflicted in 2 files, formatting only
     upstream's tip in 24, and the script in 1 (the function both sides had
     changed). The upstream commit stays in history as a parent of the
     merge.

## Environment pinned; sync script portable (2026-09-28)

Step 4 of `doc/improvement_plan.md`. The Python version was stated nowhere:
`.venv` ran 3.13, while `sync_trials.sh` created a 3.12 conda environment and
installed whatever versions were newest that day.

- `pyproject.toml` (new) states `requires-python = ">=3.12"` and the same
  dependency floors as `requirements.txt`. It is not an installable package;
  there is no build system. The suite was run on 3.12.7, in a fresh venv
  built from the lock, and on 3.13.0: 570 tests pass on both. `main.py`
  refuses an older interpreter with a clear message instead of failing
  somewhere inside an import.
- `requirements.lock` (new) pins all 22 packages, direct and transitive, at
  the versions the suite passed with. The README now installs from it.
  `requirements.txt` keeps the floors.
- `tests/test_environment.py` (new, 5 tests) fails when the three files
  disagree: the floors, a requirement missing from the lock or pinned below
  its floor, a line in the lock that is not an exact pin, or `main.py`'s
  version guard.
- `sync_trials.sh` rewritten. It now:
  - no longer sources `~/.init_conda` and no longer creates a conda
    environment. It uses `PYTHON` (default `./.venv/bin/python`), as
    `scripts/run_ollama_mapping.sh` already did, and never installs
    anything. **Anyone running it through conda must set
    `PYTHON="$(conda run -n nct2ctml which python)"`.**
  - runs with `set -euo pipefail` and stops at the first failing step, with
    that step's exit code.
  - takes a lock (`cache/sync.lock`, via `mkdir`, because `flock` is missing
    on macOS), so a second sync exits with 75. A lock left by a killed run is
    detected from its pid and taken over.
  - `cd`s to its own directory, so cron can start it from anywhere.
  - is now executable in git (it was `100644`, although the README said to
    run `./sync_trials.sh`).

  Tested with a stand-in interpreter covering: a normal run, a failing
  step, two overlapping runs, a stale lock, a missing interpreter, and a
  start from another directory.

## Provenance: what produced each file, every model call recorded, runs replayable (2026-09-28)

Before this change, a mapped trial carried nothing about how it was made.
Model, prompt variants (`GENOMIC_PROMPT` and `DIAGNOSIS_INPUT` can both be
set from the environment), code and reference files all change the output,
and temperature 0 does not make the hosted model repeatable. So a file could
be traced neither to its pipeline nor to the answer the model gave. Steps
1-3 of `doc/improvement_plan.md`.

- **`_provenance` in every mapped file.** `TrialMapManager._save` appends it
  last on all three save paths. It holds the run id, the time, the git commit
  and dirty flag, the platform and model with their settings and both prompt
  variants, and the SHA-256 of all 13 reference files the mapper reads. The
  `.prev` backup check leaves the block out, so re-mapping an unchanged trial
  still makes no backup. `accept` edits the raw text, so the block survives
  review. `bulk_convert_yaml_to_json.py` strips it from the JSON, because
  MatchMiner's `trial` resource has `allow_unknown: False` and would reject
  the load.
- **Runs.** `main.py map` and the benchmark each start a run:
  `runs/<run_id>/run.json` (command, code, model and settings, reference
  hashes, Python and package versions, call counts at the end), and
  `runs/<run_id>/llm_calls.jsonl` with one line per model call (trial, prompt,
  prompt and schema SHA-256, raw response, time taken, or the error). Each
  distinct schema is stored once under `schemas/`. For Anthropic the raw
  response now includes the request id, the model that answered and the
  token usage. Estimated from a stub run at ~5.6 KB per call, a full run is
  about 50 MB. `runs/` is gitignored but **not regenerable**: it is the only
  copy of what the model said. With no run started nothing is recorded, so
  tests leave nothing behind.
- **Replay.** `LLM_PLATFORM = "Replay"` with `NCT2CTML_REPLAY_FILE` pointing
  at a run's `llm_calls.jsonl` answers every call from the record, keyed by
  prompt and schema hash, and parses it with the recorded platform's own
  parser. It also uses the recorded platform's schema enum cap, since a
  different cap would send different schemas and every capped call would
  miss. `NCT2CTML_LLM_PLATFORM` now overrides `LLM_PLATFORM`. A prompt the run never sent raises `ReplayMiss`. Checked end to
  end: one NCT and one CTIS trial were mapped with a stub model, then
  replayed, and the replay gave identical CTML.
- **Index.** `trials.tsv` gains `mapped_at`, `mapped_run`, `mapped_commit`,
  `llm_model` and `prompt_settings` (empty for files without the block).
  `manifest.json` gains the build's `code`, `reference_sha256` for every
  reference file, `trials_by_mapping`, `trials_by_commit` and
  `reference_drift`: per reference file, the number of trials mapped against
  a different version of it.
- **Defect fixed on the way.** The CTIS age call was tagged
  `"CTIS: <number>"`, not the trial id, so its record was attributed to no
  trial. It now passes the bare number, as every other call does.

All reviewed trials and all earlier mapped output have no block, and show
as `unrecorded` in the manifest until they are re-mapped.
`tests/test_provenance.py` is new (22 tests); 565 tests pass offline.

## Gene scan: histone protein names and genes written together with their change

Reported by the user on NCT07306299 ("H3.3K27M, H3.1K27M, H3.3G34R, ...,
EGFRvIII"): H3-3A, H3C2 and EGFR were flagged gene_unsupported although the
text names them. Three changes:
- **Protein names:** ref/gene_synonym_addendum.tsv maps "H3.3" to H3-3A and
  H3-3B, and "H3.1" to H3C2 and H3C3, the H3.1 genes where K27M occurs.
  NCBI gives H3.1 to H3C3/H3C6, which is on the collision list.
- **Gene and change written together:** a gene immediately followed by a
  protein change is read as both (H3.3K27M, BRAFV600E, KRASG12C, EGFRvIII).
  Only a residue-position-residue suffix or vII/vIII/vIV splits a word, so
  CD19CAR and IL2RA are unaffected.
- **H3 mutations without a gene name:** stated histone mutations (H3K27M,
  H3K27I, H3K28M, H3G34R/V, "H3G34-mutant") name the H3 genes. H3K27a, H3
  K27-altered, K27me3 loss and EZHIP never count as support for a mutation
  criterion, because H3 K27-altered includes tumours without the mutation.

The check, the scan and the review sheet share the new code
(utils/gene_mentions.py). On the review queue (144 trials, 96
gene_unsupported flags), measured on each trial's whole text because the
arm text is not saved, so this is an upper bound: 8 flags disappear, all
false alarms, and no real flag is lost. The DMG-H3K27a trial stays flagged.
Across all cached trials the scan finds 53 more genes in 23 trials, all
correct, and loses none. Side effect: curated family aliases (RAS, NTRK,
BRCA1/2) now count as mentions in _text_mentions_gene and on the review
sheet, which changes the contradiction resolver's input for 16 gene pairs
in 5 trials. All 16 are real family mentions in exclusion text.

## Genes required although the text says absent or irrelevant

The user reported NCT05805605: "mutated NPM1 and wild type FLT-ITD", which
defines favourable-risk AML, was mapped as "FLT3 mutation" among the
qualifying alterations. That reads the gene backwards.

`review_helper.gene_status_contradictions` flags a gene whose alteration
the match tree requires while the inclusion text says the gene must be
absent or does not matter. Absent means "wild type X", "X-negative", "no X"
or "without X"; does not matter means "with or without X" or "mutant or
wild-type X". A gene the text also states positively (two routes, e.g.
MYCN amplified or not) is not flagged, and a negated criterion
('!Mutation', '!Homozygous Deletion') is not a requirement. The mapper
writes gene_status_contradiction and routes the trial to review; the review
sheet shows the sentence, and accept refuses the flag.
`review_helper flag-gene-status [--apply]` applies it to existing output.

Measured on all indexed trials: 7 trials flagged, and all 7 are real errors
when checked against the text:
- BRAF p.V600E required where "either mutant or wild-type B-RAF" is allowed;
- GATA1 required for all, where children up to 4 years are eligible
  "with/without GATA1 mutation";
- EGFR, twice, and HER2, where the text says negative;
- NPM1 and NOTCH1 as qualifying alterations where the text says "with or
  without".
The check also catches the original NCT05805605. There are 2 false alarms
among the 56 reviewed trials: two Ewing trials where "negative for EWSR1
rearrangement" sits beside an EWSR1-positive route that is only implied.
Applied at the user's go-ahead: 6 mapped trials moved to review and 1 was
flagged in review. Index: 957 mapped, 123 needs-review, 56 reviewed.

## Re-checking existing output for unsupported genes

`review_helper flag-unsupported-genes [--apply]` re-runs the mapper's own
unsupported-gene check (_flag_unsupported_genes, same scan and rules) on
CTML already written. It uses the trial's eligibility text, arm
descriptions and titles, with registry bracket escaping removed. It also
flags an expression-only gene written as a genomic criterion. Mapped trials
it flags move to the review queue. ctml/reviewed and out-of-scope trials
are never touched, and a file with curator comments is only reported.

Dry run after the alias block and the histone change: 46 trials. 34 are
mapped trials that would move to review, and 12 are already in review. All
flagged genes come from the blocked aliases or CD20, except FANCA in one
trial already in review. A first version used only the eligibility text and
also flagged 5 trials whose genes are named in arm descriptions (e.g. IDH1
and FLT3 in NCT06265545's arms). The earlier audit's count of 35 included
NCT04981509, whose FH criterion is supported by "HLRCC", the FH syndrome.

## Gene scan: 15 misread short aliases blocked; CD20 is expression-only

A queue audit found that the gene scan resolved short NCBI aliases to
unrelated genes: "CAR" (T cells) became PRKAR1A, "ICF" (informed consent
form) DNMT3B, "phase II" CD74, "CSF" (cerebrospinal fluid) CSF2, and so on.
The scan counts as support, so the unsupported-gene check passed. 35 mapped
trials carried a genomic criterion that the text supports only through one
of these words; for example, "DNMT3B any variation" appeared in 8 trials.

Each alias was checked against every whole-word use in the 1,255 cached
trials (full list with counts in src/trial_config.py). No use means the
gene: the few next to a genetic word are "phase II", "gene II sequencing",
"H3K28M in the CSF", "nucleic acid amplification testing (NAT)" and a list
item "b.". All 15 are added to blocked_gene_synonyms: CAR, II, B, CSF, ICF,
NHL, PN, JMML, SF, MCL, MI, FSH, NAT, B1, IP. After the change:
- 486 trials lose at least one spurious scan gene, and no gene is gained;
- each gene disappears only where its symbol is not written (PTPN11 stays in
  the one JMML trial that names it).

MS4A1 (CD20) joins CD274 and CD276 as expression-only. All 62 cached
mentions (41 trials) are antibody, CAR or flow targets.

Existing output is re-checked in the next step.

## Scope filter: supportive-care trials are out of scope; PTLD is a tumour

The user reported NCT06904235, which prevents chemotherapy-induced nausea and
vomiting in children with cancer. The documented policy puts supportive care
out of scope, but its condition "Chemotherapy-Induced Nausea" matched the
oncology vocabulary.

A trial is now out of scope when its registry conditions name no tumour and
its conditions, titles or keywords name a complication of cancer treatment.
Examples: nausea, GvHD, cardiotoxicity, mucositis, neutropenia, infection,
sepsis, pancreatitis, hypothyroidism, osteoradionecrosis. "Chemotherapy" and
"radiotherapy" in the conditions do not count as naming a tumour.
"Lymphoproliferative" is now a tumour stem, because a draft of the rule
excluded NCT03394365 (EBV post-transplant lymphoproliferative disease).

Measured over the 1,255 cached trials. Exactly 9 in-scope trials leave
scope, all supportive care:
- GvHD: NCT03818334, NCT05436418
- other treatment complications: NCT04195347 (pancreatitis), NCT05316922
  (hypothyroidism), NCT06055257 (osteoradionecrosis), NCT06853951
  (cardiotoxicity), NCT06857292 (neutropenia), 2025-524541-27-00 (sepsis)
- 2024-514321-39-00, the CTIS record of the nausea trial

Also covered: NCT06904235, already excluded by override. PTLD stays in
scope, and so do the lenvatinib sarcoma trial (NCT05617859, conditions
"Effectiveness; Sexuality") and HPV vaccination in healthy adolescents
(NCT06650956); the latter is a prevention question left to the curator.

## Scope filter: gene-therapy malignancy monitoring is not an oncology trial

Reported by the user: 2025-522275-28-00 collects samples from children with
metachromatic leukodystrophy, treated with OTL-200 gene therapy, to monitor
the "Risk of Malignancy Due to Insertional Oncogenesis". Its "malignancy"
was the only oncology term. "Risk of (secondary) malignancy" and "insertional
oncogenesis" are now masked. Exactly this trial changes; 1,146 remain in scope.

## Contradictory genomic trees go to review; fusion partners count as required

Reported by the user on 2023-508129-28-00 (asciminib, paediatric CML). The
mapping required BCR::ABL1 and, beside it, "no ABL1 variation", so it matched
nobody. It also put the excluded T315I on BCR. The deterministic protein
check caught that one: BCR has Ser315, while ABL1 isoform 1a (NP_005148.2,
MANE Select) has Thr315.

find_unsatisfiable_genes had two faults:
- **Partners ignored:** it ignored fusion partners, so this contradiction was
  invisible.
- **OR alternatives merged:** it merged the alternatives of an OR as if all
  were required. As a result, two reviewed trials ("EWSR1 fusion, or round
  cell sarcoma without one") were reported as contradictions.

It now walks only nested ANDs and counts a partner as required. It was also
only logged, and the trial was published regardless. The mapper now sets
genomic_contradiction and routes the trial to review, and `accept` refuses a
contradictory tree. On the current output: 1 real contradiction (this trial)
and 0 false ones, down from 2 false ones and 0 real ones before the fix.

The review sheet now says when an unverified protein change fits another gene
of the same trial ("fits ABL1: probably put on the wrong gene").

## Scope filter: follow-on studies are out of scope, as the policy says

Reported by the user: 2023-507041-28-00 is Kite's long-term follow-up of
patients already treated with gene-modified cells. Its only condition is
"Solid and Hematological Malignancies", and its match tree was empty. The
documented scope policy (2026-09-23) already puts CAR-T long-term follow-up
and drug rollover studies out of scope, because no new patient can enter
them. The filter only looked for cancer words, so it let them through.

A follow-on phrase in the titles or keywords now puts a trial out of scope:
long-term follow-up, LTFU, roll-over/rollover, continued access or
treatment, extension or continuation study. The inclusion criteria are not
used, because "prior to any study procedure" is too common. Exactly 18
in-scope trials move out, all follow-up or rollover studies; 1,147 remain in
scope. A "map" override still wins.

## Diagnoses named only in exclusion criteria; excluded diagnoses in the index

Reported by the user on 2023-504999-25-00 (CHIP-AML22): APL, myeloid
leukaemia of Down syndrome, MDS and JMML are that trial's exclusion
criteria, and the mapper had published them as eligible diagnoses. A
deterministic check (review_helper.diagnoses_only_in_exclusions) flags a
diagnosis named in the exclusion criteria and nowhere in the inclusion
criteria, title or conditions.
- **Scale:** on the full run's 1,171 trials it finds 113 diagnoses in 75
  trials, 69 of them published as mapped.
- **Accuracy:** in a sample of 10 flags, 10 are real errors.
- **Mapping:** the mapper now sets diagnosis_excluded, which routes the
  trial to review.
- **Existing output:** `review_helper flag-exclusions --apply` does the same
  for CTML already written.

Excluded diagnoses ("!Name") were not supported. build_trial_index looked the
term up as a name, found nothing, and would have published an eligible
diagnosis called "!Name". No curated trial used one until now. The excluded
node and its subtree are now removed from the eligible rows and published
with include = 0. The review helper's collect() stripped the "!" as well, so
an excluded diagnosis read as an eligible one.

Also:
- a diagnosis_off_list value holding several names ("A; B") now marks
  each name;
- the benchmark tests read the size of the answer key from ctml/reviewed
  rather than fixing it at 55, because accepted trials extend the key;
- review_log.tsv is written with \n line endings, and the log records the
  mapper's original flags even after the curator has deleted them.

464 tests pass offline.

## Scope filter: six trials in scope through phrases that name no tumour

Reported by the user: 2023-504226-18-00 is an autoimmune encephalitis trial
(satralizumab). It was in scope because the filter found "Glioma" in the
antigen name "Leucine-Rich Glioma-Inactivated 1". Listing every trial
whose conditions hold no oncology term (29) found five more such phrases:
- "tumor necrosis factor" in two juvenile idiopathic arthritis trials;
- "Memorial Sloan Kettering Cancer Center" in the keywords of a sickle cell
  trial and an aplastic anaemia trial;
- "myelom" (the myeloma stem) inside "myelomeningocele" in a spina bifida
  trial.

These phrases are now masked before the vocabulary is matched. Exactly those 6
trials change decision (1,171 -> 1,165 in scope); no other trial moves.

The index build now also drops trials listed in ctml/out-of-scope.tsv, so a
filter fix takes effect without deleting an earlier run's output. The
exception is a trial in ctml/reviewed: only a skip row in
ref/scope_overrides.tsv removes a reviewed trial. The index now holds 1,165
trials: 1,019 mapped, 91 needs-review, 55 reviewed.

About 12 of the 29 are oncology-adjacent: supportive care, cancer
prevention, and follow-up after gene therapy. The filter's documented policy
puts these out of scope, but the vocabulary cannot tell them apart; they are
left for a curator to exclude. 457 tests pass offline.

## Excluding a trial from scope takes one step

A skip row in ref/scope_overrides.tsv stopped map --all from mapping the
trial, but a copy already in cache/ctml or ctml/needs-review stayed in the
index. The index build now drops every trial with a skip row, from any
layer, and lists them in manifest.json (excluded_by_scope_override).
`review_helper exclude <trial> --reviewer --reason` adds the row and logs the
decision. With no skip rows the index is byte-identical. The scope filter
checks for oncology terms, not age: 23 mapped trials in the index are
adult-only (minimum age 18 or more). The age criteria already keep them from
matching a paediatric patient, so they are harmless in the index; exclude
them only if they should not be listed at all. 454 tests pass offline.

## Review helper (utils/review_helper.py)

HTML review sheets for ctml/needs-review and for the 3.4 audit sample, plus
a checked, logged `accept` into ctml/reviewed. No model calls. On the 99
queued trials of the full run, the 100 flagged genes break down as follows:
- 70 are not named anywhere in the trial text;
- 19 are named in the trial text but not in the arm's criteria, which is
  what the mapper checks;
- 10 are named only by an ambiguous NCBI alias (ALL/CML for BCR, ROS for
  ROS1), which the sheet shows but never counts as support;
- 1 is a near-miss spelling ("KTM2A", 2023-504694-20-00).

Of the 19 off-list diagnoses, 15 are named in the text. `accept` refuses
remaining flags, no diagnosis, unknown genes or OncoTree names, and protein
changes that fail the reference check. 451 tests pass offline.

## Enrichment prompts get a schema; "NF-1" and "NF-2" resolve (roadmap 6.9)

The mutation and CNV enrichment prompts sent no schema, so their answers were
JSON pulled out of free text. They now send MUTATION_ENRICHMENT_SCHEMA and
CNV_ENRICHMENT_SCHEMA, and merge_enriched_criteria merges only allowed values:
a variant_classification or cnv_call from the lists the prompts give, and an
exon that is a positive whole number. On a non-strict tool call the enum only
guides the model, so the check is in code, and refusals are recorded in
ENRICHMENT_REJECTED.

"NF-1" and "NF-2" were in neither synonym table. All 15 mentions in the
cached corpus (11 trials) refer to neurofibromatosis. NCBI Gene resolves
"NF-1" only to NF1 and "NF-2" only to NF2, not to the nuclear factor I genes.
Both are added to the addendum. The scan now finds NF1 or NF2 in 9 of those
11 trials. The gene-info gate was already open for all 11, so the model is
called no more often; it just sees the gene.

Found on the way: with NF1 now offered, the inclusion prompt invented an NF1
inclusion on NCT04775485, whose text names NF-1 only as an exclusion.
resolve_contradictory_genes drops an invented inclusion only when the
exclusion text names the gene, and "NF-1" did not count as naming NF1.
`_text_mentions_gene` now also accepts the curated addendum aliases
(`reference_validation.curated_aliases`), but not the full NCBI table, whose
short aliases would make any text match. The NF1 exclusion now stands, as in
the text and the key.

Dry run 3.1 replayed with 19 new calls, all answered as tool calls, 0 failed.
3 trials changed:
- NCT04775485 and NCT07110246 leave the review queue: the false NF1 flags
  are gone, and on NCT07110246 the H3 changes now verify.
- NCT05745714 gains Missense_Mutation on IL7R and JAK3. The text says
  "missense or in-frame indel", and a single classification cannot hold
  both, so an in-frame indel patient would no longer match (roadmap 7.6).
Benchmark scores are unchanged. The reviewed index is byte-identical.

431 tests pass offline; 2 live-model tests and 1 needing jsonschema are
skipped (the schemas were validated against the 2020-12 metaschema outside
the repo venv).

## Overwritten review copies are kept as backups

The reverse of D6: a run that sent a trial to review again overwrote its
existing `ctml/needs-review` copy, including any curator edits. The user's
choice: back it up first. `TrialMapManager._save` now works as follows:
- **Backup:** before writing into the review queue, a differing existing
  copy is renamed to `<trial>.yaml.prev`, then `.prev.1`, `.prev.2`, ...,
  so no backup is ever overwritten.
- **No backup when unchanged:** an identical copy is left alone, so
  re-runs do not pile up backups.
- **Mapped output:** `cache/ctml` is overwritten as before, since nobody
  edits it.

The index skips the backups and lists them in the manifest under
`review_backups`. All three save paths use it (bulk NCT, single NCT,
CTIS). 418 tests pass offline; 2 live-model tests are opt-in.

## Diagnosis answers checked against their candidate list; bulk NCT mapping routes to review

Roadmap 1.8. On Anthropic the forced tool call is not `strict`, so the
schema enum only guides the model. `filter_diagnoses` caught answers that
are not Oncotree names, but an Oncotree name from outside the branch a call
offered passed. `ai_helper.keep_candidates` now checks every diagnosis
answer, in code, against exactly the list its call sent:
- **Case-only difference:** recased to the candidate.
- **Not an Oncotree name:** dropped.
- **Valid Oncotree name from outside the offered list:** kept, written to
  the CTML as `diagnosis_off_list`, and the trial goes to
  `ctml/needs-review`.
- **Level-1 answers:** off-list ones are always dropped, because the caller
  uses them as branch keys. Before this change a valid but off-list level-1
  name would have raised a KeyError.

Run logs report the counts.

Replaying the six saved stage-2 runs (3 Haiku, 3 Sonnet; 2,585 answers)
found 4 off-list answers, all on Haiku:
- 3x "Lymphoma" (NCT02332668), dropped.
- 1x "Neuroblastoma" (NCT03838042, 1 of 3 replicates). It is named in the
  text and in the key, but stage 1 had not offered its branch.

A hard drop, as first planned, would have removed that correct answer, so a
valid off-list name goes to review instead. Benchmark scores are identical
on every trial of all six runs. On Haiku the rule sends 1 trial to review in
150 trial-runs.

Found on the way, and fixed: `map_all_trials`, the NCT path behind
`map --all`, saved every trial to `cache/ctml` without calling
`_destination_for`. A bulk run therefore never routed an NCT trial to
review for no diagnosis, an unverified protein change or an unsupported
gene. Single-trial and CTIS mapping did route. A test now pins the bulk
path. Still open (roadmap 3.0): nothing removes a trial's older copy in
`ctml/needs-review` when a later run maps it cleanly, and the index layers
let needs-review win. 404 tests pass (2 skipped).

## Cytogenetic notation translated to gene pairs, deterministically

Roadmap 1.4. Trials write fusions in ISCN notation as often as in gene
names: 132 mentions in 44 cached trials, in 34 forms, 52 of them with bands.
`utils/translocations.py` parses t() and inv(), with their spacing, colon
and comma variants and with or without bands. It resolves each rearrangement
against `ref/translocation_fusions.tsv`, 69 curated rows with a reason each,
by these rules:

1. **Bands given:** they must match a row at arm + major band. If none
   matches, the result is unresolved.
2. **No bands, one conventional row:** that row is used (inv(16) ->
   CBFB::MYH11).
3. **No bands, several rows:** only the gene every candidate shares is
   returned (t(8;14) -> MYC). If none is shared, the result is unresolved
   (t(12;22) is EWSR1::DDIT3 or MN1::ETV6).

Bands matter: inv(16)(p13.3q24.3) in one trial is CBFA2T3::GLIS2, not
CBFB::MYH11. No model is involved.

Of the 132 mentions, 119 resolve to a pair and 7 to one gene. 6 are
unresolved: 2 whose written bands contradict the standard ones,
t(1;19)(q21;p13) and t(4;11)(q11;q23), which the code does not correct; and
4 ALK variant forms not in the table.

What the table does not decide is whether a rearrangement is a criterion. In
9 of the 11 reviewed trials that mention one, the curator made no gene
criterion of it, because they are risk-group definitions or lists of
examples. So the table supplies evidence and does not add criteria. It is
used in one place now: the unsupported-gene check (1.2) counts a gene named
in cytogenetic form as supported. That removed the 4 false flags on
NCT06083883, and on the saved Haiku answers 1 flag in 1 trial remains per
replicate.

The table also resolves NCT07012447's inv(16) and t(15;17) to CBFB and PML,
the two genes the gene scan still missed. They do not yet reach the model:
prompt rule 9 tells it not to derive genes from cytogenetic notation. That
step, annotating the text with the resolved pair so the model reads it, is
roadmap 1.4b and needs a model measurement. 396 tests pass (2 skipped).

## Schema enum cap: visible, counted, set per backend

Roadmap 1.7. Measured 2026-09-24 with no model calls:
- **Benchmark:** replaying the diagnosis path over the 50 curated NCT trials
  from both Haiku 4.5 caches, the largest candidate list sent as an enum
  was 370 (NCT02813135). Stage-2 p95 was 317 and 279, and none exceeded
  400, so the cap never fired.
- **Whole corpus:** across all 1,255 cached trials, the seed branch floor
  alone reaches 438 on NCT02508038, which forces six branches. The floor
  plus its largest missing level-1 branch exceeds 320 on 33 trials;
  CNS/Brain adds the most on 27. The four largest branches sum to 406, so a
  trial with no seed can cross 400 too.

Dropping the enum used to be silent. `utils/ai_helper._one_of` now logs a
WARNING, with trial id and size, when it drops the enum, and an INFO above
80% of the cap. It counts both, and `map_all_trials` and
`map_all_ctis_trials` log the counts at the end of a run.

The cap is now set per backend (`config.SCHEMA_ENUM_MAX_VALUES`). It stays
at 400 for Ollama, LocalAI, vLLM and SGLang, which compile the schema into a
generation grammar. It is removed for Anthropic, whose forced tool call is
not `strict` and so compiles no grammar. The documented grammar limits of
Anthropic's strict mode fail with a 400 error, not silently. Benchmark
results are byte-identical before and after.

Found on the way: without `strict` the enum only guides the model on
Anthropic. The cached answers contain the off-list "Lymphoma" once per
replicate (NCT02332668). `filter_diagnoses` drops it, since it is not an
Oncotree name, but an Oncotree name from outside the candidate branch would
pass. Filtering stage-2 answers against the candidate list in code, or
switching on strict tool use, is not done yet. 381 tests pass (2 skipped).

## Benchmark covers CTIS

Roadmap 1.5. `bench/benchmark_map.py` read only the NCT keys, so the 5
curated CTIS keys were never scored and the CTIS mapper had no benchmark.
All three modes now run both registries:
- **Full mapping:** EU CT numbers go to
  `TrialMapManager.map_single_ctis_trial`.
- **`--conditions-only`:** CTIS conditions are read through
  `src.ctis.get_conditions` and go into the same `seed_and_map_diagnosis`
  and basket fallback as NCT.
- **Restricting a run:** `--source nct|ctis|all` selects a registry. Report
  rows carry their registry, and the summary gives a mean per registry.
- **Ordering:** NCT trials come first, so `--limit N` means the same as
  before.
- **Config:** the cache paths are now in config (`NCT_CACHE_PATH`,
  `CTIS_CACHE_PATH`).

Identity calibration: 55/55 at 1.00 (was 50/50). Conditions-only, NCT: dx
F1 0.74, pop P 0.92, pop R 0.78. These are identical to the previous run;
the 50 rows match. Conditions-only, CTIS: dx F1 0.17, pop P 0.40, pop R
0.27. Three of the five get no diagnosis, because CTIS writes its
conditions as sentences, and none gets a wrong one.

Adding CTIS exposed a false positive in `unsatisfiable()`. It collected every
gene under an AND, including genes inside OR alternatives, and so flagged
the two Ewing CTIS keys, which require an EWSR1 fusion in one alternative
and its absence in another. It now counts only genes that every path
through the AND requires. 373 tests pass (2 skipped).

## Retired-symbol rewrite widened to the synonym table

Roadmap 1.3. `canonical_gene` rewrote only the 15 renames between
`genes_kispi.txt` and `genes.txt`, so HIST1H3A (H3C1) and HIST2H3C (H3C14)
were dropped even though the synonym table maps both. It now also rewrites
synonym-table aliases that pass deterministic checks, which takes the set
from 15 to 4,028. Re-measured on the current ref files:

| filter | aliases left |
|---|---|
| unambiguous aliases of a panel gene | 4,879 |
| at least 4 characters | 4,295 |
| not another gene's current MANE symbol (removes TCF4, PDK1, TTF1, ...) | 4,269 |
| shape rules (removes 181) | 4,088 |
| new `ref/gene_rewrite_exclusions.tsv` (removes 61) | 4,027 |

The shape rules remove case- or punctuation-fold ambiguity, CD antigens,
family stems (PARP, HDAC, VEGF), fusion names (BCR-ABL), and PDL1 as a
variant of the blocked PD-L1.

The 4-character floor proposed in `open_issues.md` was not enough. Across the
1,255 cached trials, 15 aliases of 4 or more characters are used as something
other than a gene: JMML (22 trials), CHOP (the hospital), ICF1 (informed
consent form), ARM1, PD-1, CTLA-4 and IL-2. And 34 of the 443 four-letter
candidates are English words, contrary to the earlier estimate. Each
exclusion row records its source and reason. If the exclusion file is
missing, the widening is switched off; the check itself stays on.

Effect on current data:
- 0 of the 68 answer-key symbols and 0 of the 221 scan-path symbols
  canonicalise differently.
- 25 trials gain a newly resolving word (HER2 in 12).
- 2 of those trials gain a gene reached no other way (MEK1 -> MAP2K1).

The intended benefit, rescuing retired symbols the model writes into
`hugo_symbol`, shows up only in a mapping run and is not yet measured. Side
finding, not changed: the scan's own synonym table maps PDL1 -> CD274,
because the `!PD-L1` block covers only the hyphenated spelling. CD274 is
expression-only, so it does not reach the index as a genomic criterion.
361 tests pass (2 skipped).

## Gene scan reads fusion notation; genes the text does not support go to review

Roadmap 1.1 and 1.2. The gene list handed to the model split the criteria
on whitespace only, so a gene written inside a fusion or an unspaced list was
invisible. On the 55 reviewed trials, 12 trials lacked a curated gene in the
scan (25 trial-gene pairs), for example PICALM::MLLT10 and DEK::NUP214
(NCT06177067), and IDH1/2 and ASXL1/2 (NCT07012447).

- **Splitting:** `TrialCriteriaToGenes` now splits tokens on `::`, `-`, `/`,
  dashes, comma and semicolon.
- **Slash shorthand:** IDH1/2, CDKN2A/B, JAK1/2/3 and MYC/N expand only to
  current symbols. MYC/N gives MYCN, never MYN, an alias of PALLD.
- **Other forms:** markdown-escaped tokens (`\[ERG\]`) and the lower-case
  prefix in cCBL are now read.
- **Short parts:** a part of 3 characters or fewer counts only if it is
  itself a current symbol, so CAR, AT, ARF, H3, ALL and B7 still do not
  resolve.

Trials missing a curated gene went 12 -> 2. The two left are NCT04775485
(NF1 appears only as the syndrome "NF-1", RAF1 only as "RAF fusion") and
NCT07012447 (CBFB and PML appear only as the karyotypes inv(16) and
t(15;17)). The scan now finds 63 new trial-gene pairs in 18 trials: 21
curated, 42 named in the text but not curated, and 0 false. Across all 1,255
cached trials, every newly resolved alias is a protein name for its gene
(CD20 -> MS4A1). Known side effects: SHH now also resolves from the
medulloblastoma subgroup label "SHH-activated", and the older collision
"TLS" -> FUS is unchanged.

A gene the model returns, as `hugo_symbol` or `fusion_partner`, that the scan
did not find and the text does not spell out as a whole word is kept but
marked `gene_unsupported`. The trial goes to `ctml/needs-review`, and
`trial_genomic.tsv` reports it in `gene_check`. The whole-word fallback is
needed because fusion partners are often missing from the synonym table
(SET, RUNX1T1, DUX4, USP9X); without it the rule flags 12 genes in 7 trials
per replicate, and the 7 extra flags are all correct partners.

Measured on the saved Haiku 4.5 gene answers, two replicates, no new model
calls: 5 flags in 2 trials in each replicate. *Corrected the same day:* four
of them, FUS::DDIT3 and EWSR1::DDIT3 on NCT06083883, were first reported
here as model errors. They are correct: the text states them as
t(12;16)(q13;p11) and t(12; 22) (q13;q12), which the scan could not read. With
the translocation table (next section) they are supported, and 1 flag in 1
trial remains per replicate: FLI1 from "EWSR1-Fli" (2024-511989-36-00),
also a correct reading. On these answers the rule has not yet caught a real
error. It is kept because it costs little review and targets the MYCN
case. The MYCN case from the fusion-prompt
run (NCT06071897) does not occur in these answers, so it is not tested
here. `map_ctml_match_genomic_criteria` passes the scanned list it already
builds, so the scan is not run twice. 351 tests pass (2 skipped).

## New capability: fusion partners

CTML wrote BCR-ABL1 as OR'd single-gene nodes, so the index could not tell
an EWSR1::FLI1 trial from any EWSR1 fusion trial. The pairing is now kept
from extraction onwards.

- The genomic schema has `fusion_partner`, and prompt rule 9 asks for one
  Structural Variation entry per fusion named by both genes, and for no
  partner when one gene is named. Genes are not derived from cytogenetic
  notation.
- `reference_validation.fusion_partner` accepts a panel gene or alias, an
  exact current symbol with a MANE Select transcript (`ref/mane_genes.tsv`,
  19,364 genes), or an IG/TR locus. Off-panel aliases are not guessed:
  "CAR", as in CAR-T, is an alias of PRKAR1A, and a text-pattern pass over the
  corpus found exactly that spurious pair three times.
- The mapper keeps a partner only on a Structural Variation criterion, on a
  real gene other than the criterion's own. Otherwise the partner moves to
  `fusion_partner_unverified` and the criterion means any fusion of the gene.
  When only the partner is on the panel, the two are swapped before the panel
  filter runs. Without the swap, "USP9X-DDX3X" dropped the whole criterion,
  DDX3X included.
- `trial_genomic.tsv` gains `fusion_partner`, `fusion` ("EWSR1::FLI1") and
  `fusion_partner_check`, and a pair of panel genes is emitted from both
  sides.
- CD276 (B7-H3) joins the expression-only genes. All 11 cached mentions are
  IHC expression, and the new prompt had started emitting it as a genomic
  criterion on NCT04897321.

Measured with the production prompt on claude-haiku-4-5 over the 55
reviewed trials, two replicates each at temperature 0; a third was cut off by
the session's token limit. The new prompt names 36 pairs in 12 trials, every
one a pair the trial's text names, and all pass the check. Gene-level F1
(inclusion genes, counting a panel partner as published) is 0.601/0.606
against the old prompt's 0.613/0.615, and at most 3 trials differ between
replicates. The four trials that moved consistently account for the whole
gap (net -0.66 F1 across 55 trials). The largest term is a genuine error:
NCT06071897, -1.00, where the new prompt infers MYCN from "high-risk
neuroblastoma" (doc/open_issues.md). Next is NCT05918640, -0.45, which lists
example FET pairs "including but not limited to". The new output keeps the
partner-free EWSR1, FUS and TAF15 rows beside those pairs, so no patient is
lost there; that term comes from how partners are counted in the score.
Against these, NCT03643276 gains +0.67 and NCT06177067 +0.12. Existing index output is unchanged,
since no curated key carries a partner yet.

## Index: every mapped trial, with its review status

The index read one directory, by default `ctml/json`, a MatchMiner hand-off
queue that empties itself after ingest. It now reads `cache/ctml` (mapped),
`ctml/needs-review` and `ctml/reviewed`, a later copy of a trial replacing an
earlier one, and `trials.tsv` records `review_status`, `reviewed` and
`source_file`. That is the input set decided on 2026-09-23: every mapped
trial is searchable, and a hit on an unreviewed one is marked as such. A
single `--source` directory still works; it is reported as `reviewed` only
if it is `ctml/reviewed`. A reviewed-only build is byte-identical to before.

## Mapping: out-of-scope trials skipped, CLI fixes

- `utils/oncology_scope.py` skips trials with no oncology term in their
  conditions, keywords or titles at map time, and lists them with reasons in
  `ctml/out-of-scope.tsv`. Every trial is still pulled.
  `ref/scope_overrides.tsv` forces either decision per trial. On the current
  cache this skips 84 of 1,255 trials (49 NCT, 35 CTIS), none of them
  reviewed. The vocabulary covers the four false positives the first
  measurement found, plus insulinoma. The official title is read because
  conditions alone miss trials that name the procedure rather than the
  disease: NCT05088226's only condition is "Peripheral Blood Stem Cell
  Transplantation".
- `map --source all` maps both registries. `map --out DIR` sets the output
  directory, which defaults to the new `config.CTML_MAPPED_PATH`.
  `--test_mode` writes to `cache/ctml_test/<date>_<model>` instead of a
  hard-coded April path.
- `sync_trials.sh` covers both registries (`SOURCE=nct` for one) and
  rebuilds the index.
- The CTIS bulk loop moved from `main.py` into
  `TrialMapManager.map_all_ctis_trials`, which applies the same scope skip.

## Mapping: protein changes checked, not pattern-filtered

`_clean_protein_change_fields` kept a protein change only if it matched one
of three one-letter patterns. Nonsense changes, three-letter forms,
single-residue deletions, duplications, delins and frameshifts were removed
silently, so a trial naming a specific variant matched every variant in the
gene. It now uses `utils/protein_change.normalise`, and the value is kept as
the trial wrote it when it verifies against the reference protein. A value
that fails becomes `protein_change_unverified` with its reason, the trial
goes to `ctml/needs-review`, and the index reports it in `protein_check`.
The trailing-X wildcard convention is unchanged.

## New capability: protein changes published as checked HGVS

Trials write protein changes in literature shorthand: `V600E`, `p.G12C`,
`E746_A750del`, and, for diffuse midline glioma, `H3 K27M`. The pipeline's
VEP annotation writes HGVS on the MANE Select protein:
`ENSP00000493543.1:p.Val600Glu`. A join between the two needs one notation,
and it has to be the official one.

- `utils/protein_change.py` rewrites a stated change as HGVS three-letter
  notation. It then checks the result against the reference protein: every
  residue the notation names must be the residue at that position, a range
  must run forwards, and an insertion's flanks must be adjacent. A change
  that fails is not published in HGVS form, because a notation naming the
  wrong residue describes a different variant. The row keeps an empty
  `protein_change` and records the reason.
- Histone H3 is renumbered from the mature-protein count histone literature
  uses, so `K27M` becomes `p.Lys28Met` and `G34R` becomes `p.Gly35Arg`. The
  rule applies to proteins that begin with the H3 N-terminus, which is a
  property of the sequence rather than a list of names. The shifted residue
  is checked like any other. A change already written in three-letter code
  is HGVS numbering and is not shifted.
- Anything outside the grammar returns `unparsed` and is never guessed:
  `V600E/K`, `exon 19 deletion`.
- `ref/mane_select_proteins.tsv` holds the MANE Select v1.5 sequences for the
  1,081 panel genes that have one, plus every H3 gene. It is 860 KB and
  committed, so checking needs no network. `utils/build_protein_reference.py`
  rebuilds it, records the SHA-256 of each source file, and asserts that the
  RefSeq and Ensembl proteins are identical, which they are for all MANE
  Select genes.
- `trial_genomic.tsv` gains `protein_change_stated`, `protein_change_kind`,
  `protein_refseq`, `protein_ensembl` and `protein_check`. The manifest
  records the reference checksum and a count per check outcome. `--strict`
  fails the build on any unverified change.

The three curated changes, `p.K27M` on H3-3A, H3-3B and H3C2, all verify as
`p.Lys28Met`. As a cross-check, a Kispi sample's own VEP output had 18
protein changes on MANE panel transcripts. All 18 verified, and all 18 came
back as the identical HGVS string. So the two sides now agree character for
character.

## Defect fixed: a basket that names entities lost the basket

`_basket_wildcards` decided correctly that NCT02332668 (KEYNOTE-051, "solid
malignancy or lymphoma") and NCT07440290 (tumour-agnostic BRAF V600) are
baskets, but both callers consulted it only when no specific diagnosis had
been found. Both trials name a few entities, so they kept those entities
and lost the basket. By population they reached 2% and 3% of the patients
their keys do.

`seed_and_map_diagnosis` now adds the wildcards whenever the rule fires, as a
union with the named terms. It is not a replacement, because NCT02332668's
rule yields `_SOLID_` alone and dropping the Classical Hodgkin Lymphoma it
names would remove it from every lymphoma patient. The wildcards are added
after the model call, because the floor handed to the model must be Oncotree
nodes. Recall went 0.02 -> 0.75 and 0.03 -> 1.00, and nothing else on the
benchmark moved. The change touches 12 of 924 cached ClinicalTrials.gov
trials, and the inclusion criteria of all 12 were read by hand: each
describes a basket. This overturns the docstring's earlier claim that
NCT06607692 was an over-reach. `bench/benchmark_map.py --conditions-only`
now calls `seed_and_map_diagnosis` itself instead of restating it.

## Defect fixed: age bounds stated in prose were not read

ClinicalTrials.gov's `maximumAge` is in completed units for most sponsors
and an exclusive bound for about one in three, so the structured reading was
a year too wide on 11 of the 50 benchmark trials. Bounds stated only in
prose were not read at all. CTIS read only a minimum, so every unreviewed
CTIS trial was open-ended at the top.

- `utils.ai_helper.get_age_bounds` replaces `get_minimum_age`. The model
  reports both bounds, each with its unit as stated and whether it is
  inclusive, and takes the widest range across cohorts. The unit is not
  converted by the model, because the completed-units reading adds one unit
  of whatever the trial wrote, and that unit is a month for "<= 18 months".
- `utils/age_bounds.py` holds the rules, which are deterministic and tested
  offline. The structured minimum stays authoritative. A structured maximum
  is narrowed to `<N` only when the prose states an exclusive bound at the
  same N. Prose fills a bound only where the structured field is empty, and
  "birth" is not a minimum. Any failure of the reading step leaves the
  structured result as it was.
- CTIS gets both bounds from the call it already made.

Measured on 2026-09-23 with the production prompt on claude-haiku-4-5. Over
the 50 NCT keys, age F1 went **0.763 -> 0.919** and exact matches went
34 -> 44, with no trial worse. Over the 5 curated CTIS keys it went
0.667 -> 0.800; the "before" figure there is the minimum alone, taken from
the same answers. It costs one extra model call per ClinicalTrials.gov
trial.

## Documentation: README rewritten for this fork

The README described upstream: no CTIS, no benchmark, no index, the Miro
board and DeepWiki for upstream's code, Windows paths, and stray keyboard
text in the workflow. It now documents the real CLI (checked against
`--help`), the review queues, the flat index as the primary consumer, the
LLM backends, the benchmark modes, and the reference files.

## Benchmark: diagnoses scored by the patients they reach

`bench/benchmark_map.py` compared diagnosis *names*. A trial that matched
every B-ALL patient scored the same as one that matched none, and the
correct parent answers on NCT05366218 and NCT05748171 were scored 0.0. The
fix `doc/open_issues.md` proposed was to expand through the deployed
MatchMiner mapping file. MatchMiner is no longer the consumer, so expansion
now runs through our own Oncotree.

- `utils/build_trial_index.diagnosis_population` expands a diagnosis set to
  the nodes a patient can be coded to. Patients are coded at the most
  specific node, which is a leaf or an internal node with no ", NOS" child.
  Only 20 of 170 internal nodes have one; an osteosarcoma that is not
  subtyped further is coded `Osteosarcoma`. A leaves-only rule would have
  dropped it. `_SOLID_`/`_LIQUID_` expand as in the index.
- The report adds `pop_p`, `pop_r`, `pop_f1`, `pop_missed` and `pop_extra`.
  The name scores are kept so earlier runs stay comparable.
- `--conditions-only` writes and scores the deterministic diagnosis path
  (conditions seed plus basket rule) with no model and no network. It is the
  replay loop `doc/open_issues.md` asked for, for the half of stage 1 that
  needs no model.
- `tests/test_population_scoring.py`, 10 cases, each one the name metric got
  wrong on the curated key.

Calibration: identity 1.00; key shuffled by one P 0.15 / R 0.15. The chance
floor sits above the name metric's 0.05 because unrelated basket trials share
patients. Conditions-only baseline on 2026-09-23: by name P 0.90 / R 0.65 /
F1 0.72 (the 0.684 recorded above is the seed alone, without the basket
rule, and reproduces exactly); by population P 0.92 / R 0.75 / F1 0.76. The
population metric also exposes a failure the name metric could not grade:
two basket trials given specific terms reach 2% and 3% of their patients.

## Cleanup: upstream leftovers and a suite that could not go green

- `ref/local_trial_info.csv` — emptied to its header. It held 96 rows of
  CUHK/HKU and Korean institutional trials (87 distinct NCT ids), and five
  of them had reached the pulled corpus carrying a foreign protocol number:
  NCT03093116, NCT03157128, NCT06099366, NCT06184009, NCT06516679. None had
  been mapped or reviewed. Emptying the file does not remove them:
  `TrialPullManager.modify_trial_status_file` keeps an existing
  `local_protocol_ids` value whenever the caller passes an empty one, so a
  stale id is permanent. The five were cleared by hand from
  `cache/nct/trial_status.csv` (untracked; a `.bak` sits beside it). The file
  also gates one behaviour worth knowing about: a *closed* trial is pulled
  only if it appears here, which is how NCT03157128 entered the corpus. With
  the file empty, closed trials are not pulled. When Kispi has local trials
  to record, the header is the format.
- `src/ctml_schema.py` — the `age` default is `All`, not `Adults`. It is not
  only a placeholder the mapper overwrites: `clinical_trials_gov.map_age_group`
  returns it for any trial with no `stdAges`. That fires on none of the 924
  cached trials today, so no output changed, but in a paediatric corpus
  `Adults` is the one fallback guaranteed wrong, and `ctis.map_age_group`
  already falls back to `All`. Both registries now agree.
- `requirements.txt` — adds `anthropic`, imported lazily by the Anthropic
  backend. `doc/open_issues.md` also listed `pandas` as missing; nothing
  imports it, so it is not added.
- `tests/test_ai_helper.py` — the two tests send real prompts to the
  configured model, so on any machine without a running server the suite
  reported two errors and never went green, which is how a real regression
  there goes unnoticed. They are now opt-in with `RUN_LIVE_LLM_TESTS=1`
  rather than skipped on connection failure, because a skip that fires
  whenever the server is down also fires the day it is misconfigured. The
  offline suite is 229 tests, 2 skipped, 0 failing.
