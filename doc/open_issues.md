# Open issues

Things known to be wrong, unfinished, or undecided. Each says what it costs,
so triage does not need re-deriving. Dated entries are measurements, not
guesses.

## Correctness

### The wrong-branch problem is only half solved
Terms named outright in `conditionsModule` now force their Oncotree branch
into the second stage, but that covers 326 of 924 trials (35%), the ones whose
conditions resolve to an Oncotree term once leading and trailing qualifiers
are peeled. For the other 65% a wrong level_1 still makes the right answer
unreachable.

A single-stage prompt over all 879 display names is ~7k tokens and fits the
32k context, and would make unreachability impossible by construction. It is
not obviously better: on NCT04732065 the model was shown CNS/Brain's 126
descendants and returned 25 diagnoses where 4 were right, so 879 candidates
would likely trade a few catastrophic recall failures for many precision
failures. Settling it is a two-arm run of the existing benchmark comparing
precision and recall separately, not F1. Note that `_MAX_ENUM_VALUES` would
have to be raised for the experiment, or the schema silently drops its enum
and off-list answers become possible again.

What still fails to resolve, in rough order of tractability: word-order and
punctuation variants ("T Acute Lymphoblastic Leukemia" for
"T-Lymphoblastic Leukemia/Lymphoma"), plurals ("Malignant Peripheral Nerve
Sheath Tumors"), a diagnosis with a fusion appended ("Acute Promyelocytic
Leukemia With PML-RARA"), and conditions that are not diagnoses at all.

### The corpus contains non-oncology trials
`query.cond` is a search, not a field filter. ClinicalTrials.gov matches those
terms anywhere in the record, so a trial whose exclusion criteria say "no
history of cancer" is pulled. NCT00929006 is an endocrinology study of
luteinizing hormone pulse frequency in pubertal girls; it contains "cancer",
"tumor" and "carcinoma" somewhere in its text and nothing oncological in its
conditions, keywords or title.

The fix is a post-fetch filter on the structured conditions, applied in
`trial_pull_manager` before caching, rather than trusting the API's search. It
is cheap and it would shrink the corpus, the mapping time and the GPU bill by
whatever the true non-oncology fraction is.

Measured with a stem vocabulary over conditions + keywords + brief title:
**57 of 924 trials (6.2%)** carry no oncology term. Most are unambiguous -
warts, myasthenia gravis, PCOS, asthma, autism, haemophilia, viral infections.

But that list has real false positives, and they are the reason to review
before dropping anything:

- **NCT06368817** `Germinoma` - a malignant germ cell tumour. "germinom" was
  simply missing from the vocabulary.
- **NCT07330037** `NSCLC` - spelled only as the abbreviation.
- **NCT07656909** `Kaposiform Hemangioendothelioma` - a vascular neoplasm
  managed in paediatric oncology.
- **NCT05088226** - conditions say only "Peripheral Blood Stem Cell
  Transplantation", but it is a Bu/CY conditioning trial, i.e. leukaemia.

And a class of genuine judgement calls: supportive care for oncology patients
(virus-specific T cells post-HSCT, chemotherapy-induced cardiotoxicity), cancer
predisposition syndromes (Peutz-Jeghers, tuberous sclerosis), plasma cell
dyscrasias (AL amyloidosis), and vascular anomalies (infantile haemangioma,
lymphatic malformation). Whether MatchMiner should carry those is a policy
question, not a vocabulary one.

Because a trial that is never pulled is a trial nobody can notice is missing,
the safer shape is probably to keep pulling everything and mark non-oncological
trials so they are skipped at *map* time - that is where the GPU cost is - with
the skip list visible and reversible. A hard drop at pull time saves little
more and cannot be audited.

### A basket trial can get both the wildcard and specific diagnoses
`map_global_diagnosis_to_oncotree_term` adds condition-derived terms first and
reaches the `_SOLID_`/`_LIQUID_` path only when the eligibility mapping returns
nothing. A tumour-agnostic trial whose conditions also name specific entities -
NCT07440290 lists Erdheim-Chester Disease, NCT02332668 lists melanoma and
classical Hodgkin lymphoma - can therefore end up with the specific terms and
no wildcard, which is narrower than the trial actually is. The curated keys for
those two use the wildcards, so the benchmark will now score the difference;
whether the pipeline should suppress the seed when the broad-basket test fires
is undecided.

## Unmeasured guesses

### The 400-value enum cap
`utils/ai_helper._MAX_ENUM_VALUES` drops the enum from a schema above 400
candidates, on the reasoning that llama.cpp compiles `format` into a grammar
and hundreds of alternatives are slow to build. The threshold has never been
measured on a GPU. With the branch floor now unioning several Oncotree
branches, the candidate list can approach it. If per-trial time jumps, look
here first.

## Scoring decisions, not defects

### Parent versus ", NOS"
`bench/benchmark_map.py` compares diagnosis sets exactly, so returning
`B-Lymphoblastic Leukemia/Lymphoma` where the key holds
`B-Lymphoblastic Leukemia/Lymphoma, NOS` scores 0.0 - both are valid Oncotree
nodes, parent and child. This cost NCT05366218 and NCT05748171 their entire
diagnosis score on 2026-09-14 for answers that were essentially right.
Crediting an ancestor match is defensible; so is not crediting it, since the
parent matches more patients. It is a curation policy question.

### Run-to-run variance exceeds most single fixes
Measured 2026-09-14: the reference-validation change did exactly what was
predicted on the two trials it touched, and the overall dx F1 still fell,
because two neuroblastoma trials happened to flip branch in the same run. A
single run cannot evidence a change worth a few points. Compare per-trial, or
repeat runs.

## Answer key

- **NCT06239272 may be under-curated.** It is one of the original twelve, not
  one of the 38 added later, so it has been left alone. The trial lists 42
  conditions - every non-rhabdomyosarcoma soft tissue sarcoma subtype - and
  its eligibility is "patients with NRSTS", but the key holds 6 diagnoses.
  18 of the 42 resolve to Oncotree terms; the union with the existing key is
  20. Worth a curator's eye, since the key is what everything else is measured
  against.

## Coverage

- `src/ctis.py` has never been run against a real model. `bench/benchmark_map.py`
  reads `cache/nct` only, so every benchmark to date has been NCT-only, and the
  five curated CTIS trials in `ctml/reviewed` are never scored.
- No tests for `src/clinical_trials_gov.py` (854 lines),
  `utils/llm_platforms.py` (432) or `src/ctis.py` (250) beyond what
  `tests/test_diagnosis_branch_floor.py` covers.

## Cleanup

- **49 `print()` calls in library code** alongside loguru, including
  `print(endpoint_url)` on every model request and genomic-criteria dumps in
  `clinical_trials_gov`. `print` goes to block-buffered stdout and loguru to
  stderr, so the two interleave unpredictably and neither answers to a log
  level. This is why progress was invisible during cluster runs.
- **Reference paths hardcoded** - the gene files are done (every reader now
  goes through `config.GENE_*` and `utils/reference_validation`), but
  `trial_pull_manager.py` still opens `cache/nct` as a literal.
- **`walk()` is defined four times** - `bench/benchmark_map.py`,
  `bench/build_reviewed.py`, `tests/test_reference_validation.py`, and a
  variant in `src/match_criteria_mapper.py`. Walking a CTML match tree is a
  core operation and belongs in one place.
- **`requirements.txt` is missing `pandas` and `anthropic`**, both imported.
  A clean checkout cannot run the Anthropic backend.
- **README documents neither CTIS nor the benchmark**, though `main.py` has
  `--source {nct,ctis,all}` and `bench/` is a full harness.
- **`doc/nct_to_ctml_mapping_guide.md`** does not describe the two-stage
  level_1 mapping or the branch floor.
- **`src/ctml_schema.py` defaults `'age': 'Adults'`** in a paediatric fork.
  Harmless while the mapper overwrites it.
- **`config.py` carries ~24 commented-out `LLM_AI_MODEL` lines**, which is why
  the live setting drifted out of step with the cluster unnoticed.
- **Possibly dead, unconfirmed**: `bulk_convert_yaml_to_json.py` and
  `src/get_all_intervention_types.py` have no importers and may be standalone
  scripts still in use. `rag/llamaindex/` and `rag/simple/` are upstream
  notebooks unconnected to this pipeline. `yaml/` contains one tracked file:
  `.DS_Store`.

## Inherited from upstream

- `ref/local_trial_info.csv` holds ~97 CUHK/HKU/Korean institutional trials and
  is merged into `trial_status.csv`, mislabelling trials with foreign PIs and
  protocol ids. Needs Kispi data or emptying.
- `src/trial_pull_manager.py:329` — trials in `trial_status.csv` that the API
  stops returning are unhandled (upstream `TODO`).
- `utils/ai_helper.get_arm_criteria_mapping_prompt` is the one prompt still
  sent without a JSON schema, carrying an explicit "intentionally ... for now"
  comment. It has the same silent-discard exposure as the nine that were fixed.
