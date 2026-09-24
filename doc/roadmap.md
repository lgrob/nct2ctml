# Development roadmap

Written 2026-09-24 at commit `4f87483` (branch `kispi-paediatric`, 10 commits
ahead of `origin`). Goal: a versioned trial index that Kispi's genomics
pipeline joins directly, good enough to support trial screening in a clinical
setting.

Each step lists what "done" means in measurable terms, so a step is closed by
a number, not by an impression. Steps within a phase can run in any order
unless *Depends on* says otherwise. Open decisions are collected at the end;
the step that needs each one is marked **[D1]** etc.

Standing rules for every step:

- **Measure before and after.** A change that alters mapping output reports
  its benchmark delta per trial, on two or more replicates. Run-to-run
  variance exceeds most single fixes (see `doc/open_issues.md`).
- **Deterministic first.** Anything that can be checked by code (references,
  vocabularies, notation) is checked by code. The model proposes; code
  verifies; failures go to review, never silently to output.
- **Commit per step,** with the numbers in the message and a `CHANGES.md`
  section, and the offline suite green on the committed tree.

---

## Phase 0 - Now (hours)

| # | Step | Done when |
|---|---|---|
| 0.1 | Push `kispi-paediatric` to `origin`. | `git status` shows the branch level with `origin`. |
| 0.2 | Tag the current state as the pre-run baseline (`v0.1-prerun`). | Tag exists. Later benchmark deltas are quoted against it. |
| 0.3 | ~~Decide the mapping backend~~ **Done 2026-09-24:** Anthropic API, `claude-haiku-4-5-20251001`, forced-tool JSON, temperature 0, no thinking. | Written in `config.py`; request shape tested offline. |
| 0.4 | Live smoke test: map 3 benchmark trials with a real `ANTHROPIC_API_KEY` and compare with the benchmark scorer. This is the first live call through `utils/llm_platforms.py` rather than the measurement harness. | 3 trials mapped, no API errors, cost per trial logged. |

## Phase 1 - Fixes that change mapping output (before the full run)

These are cheap and deterministic, and each one changes what the full run
produces, so they go first. None needs the GPU.

| # | Step | Done when | Depends on |
|---|---|---|---|
| 1.1 | **Gene scan tokenisation.** Make `TrialCriteriaToGenes` find genes written as `A-B`, `A::B`, `A/B` and in comma lists. | The 12 reviewed trials whose curated genes the scan misses drop to 2 or fewer; no new false genes on the 55 keys. | - |
| 1.2 | **Unsupported genes go to review.** A model gene absent from the (fixed) scan is kept but flags the trial for `ctml/needs-review`, rather than being dropped. This is the review-routing form of the gate measured in `open_issues.md`. | The MYCN case (NCT06071897) and the old CD276 case are routed; the number of reviewed trials routed is reported. | 1.1 |
| 1.3 | **Widen the retired-symbol rewrite set** with the measured 4-character floor, so `HIST1H3A`/`HIST2H3C` resolve to panel genes. | DMG trials keep their histone genes; a test pins that `ALL`, `AT`, `ARF`, `H3` are still not rewritten. | - |
| 1.4 | **Translocation table.** `ref/translocation_fusions.tsv`: unambiguous t()/inv() to gene pair, one reason per row; ambiguous ones (t(X;18)) stay gene-level. Applied deterministically after extraction. | 31 NCT trials stating a translocation are checked by hand against the output; every added pair is one the text supports. | - |
| 1.5 | **Benchmark covers CTIS.** `bench/benchmark_map.py` reads `cache/ctis` as well, so the 5 curated CTIS keys are scored. | Report has 55 rows; CTIS rows show non-trivial scores. | - |
| 1.6 | **Answer keys carry fusion partners.** A curator adds partners to the keys of trials whose text names pairs (about 9 reviewed trials), and the scorer compares pairs. | Partner precision/recall is a reported column. | curator time **[D4]** |
| 1.7 | **Guard against the enum cap.** Log when a stage-2 candidate list approaches `_MAX_ENUM_VALUES` (400), and count occurrences on the full corpus offline. | Count known; cap raised or kept with a reason. | - |

## Phase 2 - Finish the stage-2 diagnosis experiment

Stage 2 over-generates diagnoses, which is the largest measured weakness.
The replay harness exists (`stage2_harness.tar.gz`); one Haiku baseline
replicate is complete. About 1.8M model tokens are needed per five-arm
replicate, over the per-session limit of 2.0M, so each replicate runs in its
own sub-agent.

| # | Step | Done when | Depends on |
|---|---|---|---|
| 2.1 | Fix the seed-subtree arm so its floor includes sibling branches; it lost Ganglioneuroblastoma on neuroblastoma trials. | Offline test on the neuroblastoma trials passes. | - |
| 2.2 | Complete replicate 1 and run replicates 2 and 3, all arms, all 50 trials, on Haiku. | 3 complete replicates; mean and spread per arm. | 2.1 |
| 2.3 | Run baseline plus the best arm on the Sonnet-class model. | Model effect separated from arm effect. | 2.2 |
| 2.4 | Choose an arm only if it beats baseline outside the spread, on population recall first and precision second. Ship it with offline tests. | Patch merged, or "no arm wins" recorded with the numbers. | 2.2 |
| 2.5 | Optional: the single-stage run over all 879 Oncotree names (see "wrong-branch problem"). | Precision and recall reported separately. | 2.2 |

## Phase 3 - Full-corpus mapping run

| # | Step | Done when | Depends on |
|---|---|---|---|
| 3.1 | Dry run on the 55 benchmark trials with the final code and backend. | First real `bench/report.json` (replacing the identity calibration); cost and time per trial recorded. | Phase 1, 2.4, 0.4 |
| 3.1a | Consider the Message Batches API for 3.2: asynchronous and cheaper per token than live calls, and the run does not need live answers. Needs a batch submit/collect path in `llm_platforms`. | Decision recorded with the cost difference. | 3.1 |
| 3.2 | Full run: `map --all --source all` over the in-scope corpus (about 1,170 trials). | Every in-scope trial is in `cache/ctml` or `ctml/needs-review`; failures listed. | 3.1 |
| 3.3 | Build the index from the three layers and tag it as the first release (`index-2026.MM.DD`) with its manifest. | Manifest checksums recorded; review-status counts reported. | 3.2 |
| 3.4 | Audit the run: count needs-review reasons, unverified protein changes and fusion partners, out-of-scope skips, and spot-check 20 unreviewed trials at random against their text. | Audit note in `doc/`, with an estimated error rate for unreviewed rows. | 3.3 |

## Phase 4 - Consumer: matching from the genomics pipeline

A separate small package (its own repository) that reads a released index
and the per-sample pipeline outputs, and knows nothing about registries.

| # | Step | Done when | Depends on |
|---|---|---|---|
| 4.1 | Define the input contract: `<sample>_snv.tsv` (CSQ_SYMBOL, CSQ_HGVSp, CSQ_MANE_SELECT), `<sample>_cnv.prioritized.tsv`, `<sample>_sv.prioritized.tsv`, the RNA fusion file, the OncoTree code and the age at the relevant date. | A written schema plus synthetic test fixtures (no patient data in either repo). | - |
| 4.2 | Joins: OncoTree code to `trial_diagnosis`; gene and HGVS string to `trial_genomic`; fusion pair matched unordered; age against the inclusive/exclusive bounds; `include=0` rows exclude a trial. | Offline tests per join, including a fusion reported from the partner's side. | 4.1 |
| 4.3 | Variant eligibility rules (which SNVs/CNVs count) as parameters, defaults set by the lab **[D2]**. | Rules configurable, and recorded in each output. | 4.2, [D2] |
| 4.4 | Output: ranked candidate trials, each with the rows that fired, the review status, the index release and its checksum. Unreviewed trials go only to the curator view **[D3]**. | Report reproducible from (sample files, index release). | 4.2, [D3] |
| 4.5 | Retrospective check on past tumour-board cases: compare the candidate lists with the trials the board actually discussed. | Recall against board decisions reported; misses classified by cause. | 4.4, 3.3 |

## Phase 5 - Curation loop

| # | Step | Done when | Depends on |
|---|---|---|---|
| 5.1 | Review queue ordering: needs-review first, then unreviewed trials that matched real samples, then open-to-accrual trials by Kispi relevance. | Queue script produces the ordered list from the index and match logs. | 3.3, 4.4 |
| 5.2 | Grow the answer key from 55 to about 100 trials, deliberately including CTIS, basket, fusion-defined and age-edge trials. | New keys curated against full trial text; key changes logged as before. | [D4] |
| 5.3 | Frequency-weighted population score from the OncoTree codes Kispi has actually assigned. | `pop_r` reads as "share of our patients". | code list from the lab |

## Phase 6 - Clinical-grade hardening

This phase runs alongside Phases 3-5. It is what turns a working tool into
something a diagnostic lab can defend.

| # | Step | Done when | Depends on |
|---|---|---|---|
| 6.1 | **Intended use statement:** the index is a screening aid; eligibility is decided on the protocol by a clinician. Agree the regulatory framing with QA **[D5]**. | Signed-off one-page document. | [D5] |
| 6.2 | **Release process:** index releases are tagged and immutable, with a manifest (inputs, reference checksums, code commit, model id, benchmark scores). Reports cite a release. | Script produces a release; one release made. | 3.3 |
| 6.3 | **Regression gates in CI:** offline suite, the `--conditions-only` benchmark at a floor, `build_trial_index --strict` on reviewed trials. | CI fails on a drop below the recorded floor. | - |
| 6.4 | **Reference update procedure** for OncoTree, MANE (`build_protein_reference`), the panel and the synonym tables: rebuild, diff, benchmark, release. | Written procedure; one dry run on the next MANE release. | - |
| 6.5 | **Test coverage** for `src/clinical_trials_gov.py`, `src/ctis.py`, `utils/llm_platforms.py` (mocked model). | Each has tests on its main paths. | - |
| 6.6 | **Logging:** replace the `print()` calls in library code with loguru at levels; keep one run log per mapping run with the model id and prompt versions. | No `print` in `src/`/`utils/` library paths; the run log is archived with each release. | - |
| 6.7 | **Remove upstream leftovers:** MatchMiner-only schema fields, Hong Kong recruitment text, `bulk_convert_yaml_to_json.py` if unused. | Leftovers gone, with tests green. | - |

## Phase 7 - Later refinements (take as capacity allows)

| # | Step | Note |
|---|---|---|
| 7.1 | Age judgement cases: neuroblastoma risk-definition ages, site-dependent limits (ALLTogether). | Needs a curation rule first. |
| 7.2 | Measure the enum cap and grammar build time on the GPU backend. | Only if the backend is llama.cpp/Ollama. |
| 7.3 | Remaining condition-string variants: word order, plurals, diagnoses with a fusion appended. | See "wrong-branch problem". |
| 7.4 | Per-arm (cohort) diagnoses in the index and the benchmark. | The benchmark scores only the global match today. |

---

## Decisions needed

| id | Decision | Options | Needed by |
|---|---|---|---|
| D1 | ~~Mapping backend~~ | **Decided 2026-09-24:** Claude Haiku 4.5 via the Anthropic API (about $200 for the corpus, extrapolated). Sonnet-class is compared in step 2.3 and adopted only on replicated numbers. | done |
| D2 | Which SNVs and CNVs count as matchable | For example OncoKB (likely) oncogenic, the lab's own tiering, impact class; amplification threshold relative to ploidy | 4.3 |
| D3 | Where unreviewed-trial hits may appear | Curator view only, or tumour-board report flagged as unreviewed | 4.4 |
| D4 | Curator time | Who reviews, and a target review rate | 1.6, 5.2 |
| D5 | Regulatory framing | Agreed with QA/regulatory for the intended setting | 6.1 |

## Suggested order

0.1-0.4, then Phase 1 (1.1 -> 1.2, others in parallel), Phase 2, then
Phase 3. Phase 4 can start at 4.1-4.2 at any time on synthetic fixtures;
4.3-4.5 need [D2], [D3] and a released index. Phase 6 starts now with 6.3
and 6.6, and 6.1/6.2 must be done before any output is used for a real
patient.
