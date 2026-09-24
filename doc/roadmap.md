# Development roadmap

First written 2026-09-24 at commit `4f87483`. Updated 2026-09-24 at `8ecaef7`
(branch `kispi-paediatric`, 19 commits ahead of `origin`, not pushed). Goal: a
versioned trial index that Kispi's genomics pipeline joins directly, good
enough to support trial screening in a clinical setting.

Each step lists what "done" means in measurable terms, so a step is closed by
a number, not by an impression. Steps within a phase can run in any order
unless *Depends on* says otherwise. Open decisions are collected at the end;
the step that needs each one is marked **[D1]** etc. Measurements behind
every closed step are in `CHANGES.md`.

Standing rules for every step:

- **Measure before and after.** A change that alters mapping output reports
  its benchmark delta per trial, on two or more replicates. Run-to-run
  variance exceeds most single fixes (see `doc/open_issues.md`).
- **Deterministic first.** Anything that can be checked by code (references,
  vocabularies, notation) is checked by code. The model proposes; code
  verifies; failures go to review, never silently to output.
- **Recall first.** A change that loses curated diagnoses or genes in every
  replicate is not adopted for a precision gain, however large.
- **Commit per step,** with the numbers in the message and a `CHANGES.md`
  section, and the offline suite green on the committed tree.

---

## Status on 2026-09-24

| Phase | State |
|---|---|
| 0 - Now | 0.3 done. **0.1 (push) is overdue:** 19 commits exist only on this machine. 0.2 and 0.4 open. |
| 1 - Deterministic fixes | 1.1-1.5, 1.7, 1.8, 1.9 done; 1.4b measured and not adopted. Open: 1.6 (curator time). |
| 2 - Stage-2 diagnosis | Closed as measured: no narrowing arm (2.4) and no model swap (2.3, 2.6) beats production without losing curated diagnoses. Production stage 2 stays. Open: 2.7 (quote grounding) and optional 2.5. |
| 3 - Full run | 3.0 and 3.1 done (3.1 through the analysis environment; diagnosis recall 0.938). 3.2-3.4 need 0.4 (live smoke test with an API key). |
| 4-7 | Not started. 4.1-4.2 can start on synthetic fixtures at any time. |

The offline suite has 423 tests (2 live-model tests are opt-in). Conditions-only
benchmark: NCT diagnosis F1 0.74, population P 0.92 / R 0.78; CTIS diagnosis F1
0.17. Production diagnosis path on Haiku (roadmap 1.9 baseline, 3 runs):
population recall 0.942, precision 0.798, name F1 0.741.

---

## Phase 0 - Now (hours)

| # | Step | Done when |
|---|---|---|
| 0.1 | **Push `kispi-paediatric` to `origin`.** Do this first: the branch carries all of the Phase 1 and Phase 2 work. | `git status` shows the branch level with `origin`. |
| 0.2 | Tag the current state as the pre-run baseline (`v0.1-prerun`). | Tag exists. Later benchmark deltas are quoted against it. |
| 0.3 | **Done.** Mapping backend: Anthropic API, `claude-haiku-4-5-20251001`, forced-tool JSON, temperature 0, no thinking. Confirmed by 2.3 and 2.6. | Written in `config.py`; request shape tested offline. |
| 0.4 | Live smoke test: map 3 benchmark trials with a real `ANTHROPIC_API_KEY` and compare with the benchmark scorer. This is the first live call through `utils/llm_platforms.py`; all measurements so far went through the replay harness. | 3 trials mapped, no API errors, cost per trial logged. |

## Phase 1 - Deterministic fixes that change mapping output

These are cheap, and each one changes what the full run produces, so they go
before it.

| # | Step | Result / done when | Depends on |
|---|---|---|---|
| 1.1 | **Done.** Gene scan reads fusion notation (`A::B`, `A-B`, `A/B`), lists and slash shorthand. | Trials missing a curated gene: 12 -> 2 of 55; 63 new finds, 0 false. The 2 left are a syndrome name and karyotypes. | - |
| 1.2 | **Done.** A model gene or partner the text does not support is kept as `gene_unsupported` and routed to `ctml/needs-review`; the index reports it in `gene_check`. | On saved Haiku answers: 1 flag in 1 trial per replicate (a correct reading of "EWSR1-Fli"). The flag has not yet caught a real error; it costs little review. | 1.1 |
| 1.3 | **Done.** Retired-symbol rewrite widened from 15 to 4,028 aliases with shape rules and `ref/gene_rewrite_exclusions.tsv`. A bare 4-character floor was unsafe (JMML, CHOP, PD-1, 34 English words). | 0 of 68 key symbols change; `ALL`, `AT`, `ARF`, `H3`, `CAR`, `PD-L1` refused (tests). | - |
| 1.4 | **Done.** `utils/translocations.py` + `ref/translocation_fusions.tsv` (69 curated rows) turn t()/inv() into gene pairs deterministically; bands must match, ambiguous bare forms give only the shared gene or nothing. Used as support evidence, not to create criteria. | 132 cached mentions: 119 pairs, 7 single genes, 6 unresolved. Removed 4 false `gene_unsupported` flags on NCT06083883. | - |
| 1.4b | **Measured, not adopted (2026-09-24).** No recall gain: the target genes are exclusion-side and already found. Changes only fusion pairing, which cannot be scored before 1.6. Patch kept outside the repo. Originally: **Translocations reach the model.** Annotate each resolved rearrangement in the text sent to the genomic prompt (`t(15;17) [PML::RARA]`) and rewrite prompt rule 9 to use the annotation; the model still decides whether it is a criterion (the parser finds rearrangements in 7 reviewed trials; in 5 the key has none of the translocation genes). | Measured on the 7 trials and all 55, 2 replicates, against the current prompt: recall gain on NCT07012447 (CBFB, PML) or NCT03643276 without new false criteria in the other 5. | 1.4 |
| 1.5 | **Done.** Benchmark covers CTIS (`--source nct\|ctis\|all`); per-registry means. Also fixed a false positive in the unsatisfiable-tree check. | 55/55 at identity; NCT means unchanged; CTIS conditions-only F1 0.17. | - |
| 1.6 | **Answer keys carry fusion partners.** Also unblocks re-scoring the kept 1.4b patch, which mainly changes pairing. A curator adds partners to the keys of trials whose text names pairs (about 9 reviewed trials), and the scorer compares pairs. | Partner precision/recall is a reported column. | curator time **[D4]** |
| 1.7 | **Done.** Enum cap logged and counted; set per backend (400 for grammar-compiling backends, none for Anthropic). | Benchmark max 370, cap never fired; 1 corpus trial reaches 438 on the seed floor alone. | - |
| 1.9 | **Done.** Prompts and CTML no longer depend on the hash seed (0 of 476 prompts differ). Diagnosis candidates use a fixed SHA-256 shuffle; alphabetical and tree order were measured and lose recall. New baseline: diagnosis recall 0.942, precision 0.798, name F1 0.741; genes F1 0.650; ages F1 0.899. Originally: **Deterministic prompts.** Sort every list printed into a prompt: the Possible GeneList (`extract_official_gene_symbols`) and the level-1, stage-1 and stage-2 candidate lists. Today they print in set order, which follows PYTHONHASHSEED, so production prompts differ run to run (16 of 45 genomic answers changed with the order alone). Then re-baseline: the benchmark numbers so far are for the seed-0 ordering. | Prompt text byte-identical across PYTHONHASHSEED 0/1/2 (test). Conditions-only benchmark unchanged. Diagnosis and gene benchmark re-run, 2 replicates, as the new baseline; the change from the seed-0 numbers is reported. | - |
| 1.8 | **Done.** **Candidate lists enforced in code.** Result: 4 off-list answers in 2,585 on the six saved runs; the one valid name (Neuroblastoma, NCT03838042) was correct, so valid off-list names go to review instead of being dropped; scores unchanged. Also fixed: bulk `map --all` never routed NCT trials to review. On Anthropic the enum only guides the model (the tool is not `strict`): an Oncotree name from outside the call's candidate list would pass. Drop and log any stage-1/stage-2 answer not in that call's list, or enable strict tool use if its grammar limits allow. | Off-list answers counted on the cached runs; 0 reach the CTML; benchmark unchanged or better. | - |

## Phase 2 - Stage-2 diagnosis over-generation

Stage 2 emits about 2.2 diagnoses for every curated one. Everything tried so far is
measured and rejected (details and per-trial losses in `CHANGES.md` and
`stage2_arms_report.md` / `stage2_sonnet_report.md`, kept outside the repo):

- **Narrowing arms (2.4):** the seed subtree, level-2-first, a verify pass, and
  a combination. Best precision gain +0.025, from 4 trials. Every arm loses
  curated diagnoses in all 3 replicates.
- **Sonnet 5 for stage 2 (2.6):** name F1 +0.09 and precision +0.036, but it
  loses 5 curated diagnoses on 3 trials in every replicate (2 of them named
  in the text), at 2.1x the diagnosis-path cost.
- **Named-in-text floor (offline):** adding back every candidate the text
  names adds about 26 diagnoses per run with 0-1 correct.

The harness is `stage2_harness_v3.tar.gz`: replay of the production path,
per-arm patches, and `STAGE2_ROUTE` for per-stage model routing. Each
five-arm Haiku replicate needs close to the 2.0M per-session model-token limit, so
replicates run in separate sub-agents (part 1: baseline + verify; part 2:
the other arms from the part-1 cache).

| # | Step | Result / done when | Depends on |
|---|---|---|---|
| 2.1 | **Done.** Seed-subtree arm keeps level-2 siblings; Ganglioneuroblastoma no longer lost. | Offline check passed; not lost in any replicate. | - |
| 2.2 | **Done.** 5 arms x 3 replicates x 50 trials on Haiku, 0 failed calls. | Baseline replicate range <= 0.004 on every metric. | 2.1 |
| 2.3 | **Done.** Model comparison: Haiku 4.5 / Sonnet 5 / Opus 5.5, 2 replicates. No model improves recall; Sonnet +0.10 name F1 at about 2x; Opus about 4.5x for nothing measurable. | Recorded. | - |
| 2.4 | **Done: no arm wins.** | Recorded with the numbers. | 2.2 |
| 2.6 | **Done: not adopted.** Sonnet 5 for stage 2 only. Revisit only if curator time becomes the binding constraint. | Recorded with the numbers. | 2.4 |
| 2.7 | **Quote-grounded diagnoses.** The model returns, per diagnosis, the words from the text it relied on. Code checks (a) the quote is verbatim in the text after whitespace/markdown normalisation (else the trial goes to review), and (b) how the quote relates to the answer via `canonical_diagnosis` and the Oncotree lineage: *named* (quote names it), *implied* (quote names an ancestor), or *inferred* (neither; flagged). Nothing is dropped. Then test, offline on the recorded quotes, whether collapsing subtypes that are only *implied* by a parent quote to that parent raises precision without losing patients (population metric). The same quote check applies to exclusion criteria (the quote must lie in the exclusion section) and to age bounds (the number must appear in the quote). | First measure: quote failure rate (not verbatim) on Haiku, 50 trials, 1 replicate; stop if above about 10%. Then 3 paired replicates against baseline: recall no worse in any replicate, and the named/implied/inferred split reported for correct vs spurious diagnoses. | 2.2 |
| 2.5 | Optional: a single-stage run over all 879 Oncotree names (see "wrong-branch problem"). | Precision and recall reported separately. | 2.2 |

## Phase 3 - Full-corpus mapping run

| # | Step | Done when | Depends on |
|---|---|---|---|
| 3.0 | **Done (D6: keep and report).** The review copy stays published; the index sets `layer_conflict` and writes `layer_conflicts.tsv`. Originally: **Stale review copies.** A trial routed to `ctml/needs-review` in one run and mapped cleanly in a later one keeps its old review copy, and the index publishes it (needs-review overrides mapped). Decide: remove the stale copy on a clean remap (risk: a curator may be editing it), or have the index prefer the newer file, or flag the conflict. | Rule chosen **[D6]**; test pins it; the index reports conflicts. | [D6] |
| 3.1 | **Done 2026-09-24** through the analysis environment's model access (no API key yet): 55/55, NCT diagnosis recall 0.938, gene F1 0.599, age F1 0.919, $0.10/trial at list price; found and fixed the H3 HGVS one-letter rejection. Originally: Dry run on the 55 benchmark trials with the final code and backend. | First real `bench/report.json` (replacing the identity calibration); cost and time per trial recorded; diagnosis recall within the 1.9 baseline range (0.942). | 0.4 |
| 3.1a | Consider the Message Batches API for 3.2: asynchronous and cheaper per token than live calls, and the run does not need live answers. Needs a batch submit/collect path in `llm_platforms`. | Decision recorded with the cost difference. | 3.1 |
| 3.2 | Full run: `map --all --source all` over the in-scope corpus (about 1,170 trials). | Every in-scope trial is in `cache/ctml` or `ctml/needs-review`; failures listed; enum-cap and off-list counts from the run log reported. | 3.1 |
| 3.3 | Build the index from the three layers and tag it as the first release (`index-2026.MM.DD`) with its manifest. | Manifest checksums recorded; review-status counts reported. | 3.2 |
| 3.4 | Audit the run: count needs-review reasons (no diagnosis, unverified protein change, unsupported gene), fusion partners, out-of-scope skips, and spot-check 20 unreviewed trials at random against their text. | Audit note in `doc/`, with an estimated error rate for unreviewed rows. | 3.3 |

If 2.7 lands before 3.2, it goes into the full run; it does not block it.

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
| 5.2 | Grow the answer key from 55 to about 100 trials, deliberately including CTIS (only 5 today, conditions-only F1 0.17), basket, fusion-defined, translocation-defined and age-edge trials. | New keys curated against full trial text; key changes logged as before. | [D4] |
| 5.3 | Frequency-weighted population score from the OncoTree codes Kispi has actually assigned. | `pop_r` reads as "share of our patients". | code list from the lab |

## Phase 6 - Clinical-grade hardening

This phase runs alongside Phases 3-5. It is what turns a working tool into
something a diagnostic lab can defend.

| # | Step | Done when | Depends on |
|---|---|---|---|
| 6.1 | **Intended use statement:** the index is a screening aid; eligibility is decided on the protocol by a clinician. Agree the regulatory framing with QA **[D5]**. | Signed-off one-page document. | [D5] |
| 6.2 | **Release process:** index releases are tagged and immutable, with a manifest (inputs, reference checksums, code commit, model id, benchmark scores). Reports cite a release. | Script produces a release; one release made. | 3.3 |
| 6.3 | **Regression gates in CI:** offline suite, the `--conditions-only` benchmark at a floor (NCT F1 0.74), `build_trial_index --strict` on reviewed trials. | CI fails on a drop below the recorded floor. | - |
| 6.4 | **Reference update procedure** for OncoTree, MANE (`build_protein_reference`), the panel, the synonym tables, the rewrite exclusions and the translocation table: rebuild, diff, benchmark, release. | Written procedure; one dry run on the next MANE release. | - |
| 6.5 | **Test coverage** for `src/clinical_trials_gov.py`, `src/ctis.py`, `utils/llm_platforms.py` (mocked model). | Each has tests on its main paths. | - |
| 6.6 | **Logging:** replace the `print()` calls in library code with loguru at levels; keep one run log per mapping run with the model id and prompt versions. | No `print` in `src/`/`utils/` library paths; the run log is archived with each release. | - |
| 6.7 | **Remove upstream leftovers:** MatchMiner-only schema fields, Hong Kong recruitment text, `bulk_convert_yaml_to_json.py` and `ctml/json` (written, read by nothing), and the README's `ctml/pending` hand-authoring path if local trials are not planned. | Leftovers gone, README and workflow diagram updated, tests green. | - |
| 6.8 | **Harness in the repo:** move the replay harness (`stage2_harness_v3`) into `bench/replay/` with its caches' checksums, so every Phase 2 number can be re-run from the repository. | `python -m bench.replay --arm baseline` reproduces a recorded replicate from its cache exactly. | - |

| 6.9 | Give the mutation and CNV enrichment prompts a JSON schema; resolve "NF-1" to NF1 in the gene scan if it does not collide with the nuclear factor I aliases. | Enrichment answers arrive as tool calls; the 3.1 NF1 false flags disappear with no new rewrite collisions. | - |

## Phase 7 - Later refinements (take as capacity allows)

| # | Step | Note |
|---|---|---|
| 7.1 | Age judgement cases: neuroblastoma risk-definition ages, site-dependent limits (ALLTogether). | Needs a curation rule first. |
| 7.2 | Measure the enum cap and grammar build time on the GPU backend. | Only if the backend is llama.cpp/Ollama. |
| 7.3 | Remaining condition-string variants: word order, plurals, diagnoses with a fusion appended; CTIS sentence-style conditions (3 of 5 CTIS keys get no diagnosis from conditions). | See "wrong-branch problem". |
| 7.4 | Per-arm (cohort) diagnoses in the index and the benchmark. | The benchmark scores only the global match today. |
| 7.5 | Translocation table: the 4 ALK variant forms and other unresolved notations from the corpus. | 6 of 132 mentions unresolved today. |

---

## Decisions needed

| id | Decision | Options | Needed by |
|---|---|---|---|
| D1 | ~~Mapping backend~~ | **Decided:** Claude Haiku 4.5 via the Anthropic API. Sonnet 5 (whole path, and stage 2 only) and Opus 5.5 measured and not adopted: none improves recall. | done |
| D2 | Which SNVs and CNVs count as matchable | For example OncoKB (likely) oncogenic, the lab's own tiering, impact class; amplification threshold relative to ploidy | 4.3 |
| D3 | Where unreviewed-trial hits may appear | Curator view only, or tumour-board report flagged as unreviewed | 4.4 |
| D4 | Curator time | Who reviews, and a target review rate | 1.6, 5.2 |
| D5 | Regulatory framing | Agreed with QA/regulatory for the intended setting | 6.1 |
| D6 | ~~Stale `ctml/needs-review` copy after a clean remap~~ | **Decided 2026-09-24:** keep it, keep publishing it, report the conflict. | done |

## Suggested order

1. 0.1 (push) now, then 0.2.
2. 0.4 (needs the API key).
3. 3.1 dry run, then 3.2-3.4.
4. 2.7 alongside 3.1, entering the full run only if it is measured in time.
5. Phase 4 at 4.1-4.2 at any time on synthetic fixtures; 4.3-4.5 need [D2],
   [D3] and a released index.
6. Phase 6 starts with 6.3, 6.6 and 6.8. 6.1 and 6.2 must be done before any
   output is used for a real patient.
