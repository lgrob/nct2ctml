# Changes from upstream nct2ctml

This is a fork of [sumedhasaxena/nct2ctml](https://github.com/sumedhasaxena/nct2ctml),
Copyright 2026 The University of Hong Kong, licensed under Apache-2.0.
Modified by Kinderspital Zürich (Kispi) for paediatric oncology.

Per Apache-2.0 §4(b), modified files carry a notice at the top. This file
records what changed and why.

## Retargeting

Upstream was built for adult oncology at HKU/CUHK in Hong Kong. This fork
targets paediatric oncology worldwide.

- `src/trial_config.py` — paediatric condition terms, `std_ages = ['CHILD']`,
  regions emptied for worldwide coverage. Note that the age filter, not the
  condition list, is what actually restricts to paediatric trials.
- `src/trial_pull_manager.py` — `_build_query_term()` composes the
  `AREA[StdAge]` filter; worldwide handling when no region is set.

## New capability

- `src/ctis_pull_manager.py` — ingests the EU Clinical Trials Information
  System, which upstream does not cover. 331 trials cached, 271 with no
  ClinicalTrials.gov record.
- `src/ctis.py` — maps CTIS records to CTML. Shares everything downstream of
  criteria extraction with the ClinicalTrials.gov path.
- `utils/build_gene_synonyms.py` — rebuilds the gene synonym table from NCBI
  Gene, replacing an undated snapshot.
- `bench/` — scores automated mapping against hand-curated CTML.
- `utils/llm_platforms.py` — added `AnthropicPlatform` alongside the
  self-hosted backends.
- `main.py` — `pull` and `map` take `--source {nct,ctis,all}`, and `pull`
  takes `--ct_number` for a single EU trial.
- `src/trial_map_manager.py` — `map_single_ctis_trial()` as a separate entry
  point, since the two registries publish different documents and local trial
  info is keyed on NCT ids. Synonym loading also merges
  `ref/gene_synonym_addendum.tsv`.
- `src/trial_criteria_to_genes.py` — blocked and contextual synonyms. Aliases
  that in trial text overwhelmingly mean something other than the gene never
  resolve through the NCBI table; a blocked alias can still resolve when
  supporting keywords appear nearby.
- `utils/ai_helper.py` — a JSON schema for every prompt, not just genomic
  criteria, so answers are constrained rather than requested in prose. Where
  a prompt restricts the answer to a candidate list the schema enumerates it,
  which makes an off-list answer impossible to emit. Also `get_minimum_age()`,
  which reads an age bound out of free text for CTIS, which publishes no
  structured age field.
- `utils/reference_validation.py` — validates Oncotree diagnoses and HUGO
  symbols against the reference files, rewrites Oncotree codes and retired
  gene symbols, and reads diagnoses straight out of `conditionsModule` before
  any model is asked. MatchMiner's `_SOLID_` and `_LIQUID_` wildcards pass
  through: they are not Oncotree display names but they are valid CTML, and
  they are how a basket trial is expressed without enumerating 879 terms that
  would go stale on the next Oncotree release.
- `scripts/run_ollama_mapping.sh`, `doc/cluster_setup.md` — running the
  mapping on a Slurm GPU cluster with Ollama under Apptainer.
- `bench/benchmark_map.py`, `bench/build_reviewed.py`, `bench/curations.py`,
  `bench/README.md`, `bench/report.json` — the benchmark harness, its scores,
  and its 50-trial answer key, whose
  match criteria are hand-written in `curations.py` and combined with the
  pipeline's deterministic, non-LLM mapping of the cached record.

## Defects fixed

These are upstream bugs, fixed here and worth reporting back.

- `src/trial_data_helper.py` — `check_if_recruiting_in_any_region` raised
  `KeyError` on trials where ClinicalTrials.gov omits per-location `status`,
  which it does for any non-recruiting trial. The README's own example
  (NCT03997435) crashed.
- `src/trial_pull_manager.py` — the update loop used a stale variable from an
  earlier loop, so re-syncing would have written the wrong trial's data.
- `src/clinical_trials_gov.py` — age parsing assumed years and dropped any
  minimum age expressed in months, weeks or days. 248 of 718 trials with a
  stated minimum lost it.
- `src/match_criteria_mapper.py` — genomic criteria could be emitted asserting
  a gene both present and absent in the same AND branch, producing a trial
  that matches zero patients. Now detected and resolved by cause rather than
  by rule of thumb, because the three causes need opposite treatment: a
  disease name misread as a genomic exclusion (drop the exclusion), genuine
  alternative cohorts where the inclusion text itself negates the gene (drop
  both, since the net requirement is none), and an inclusion the model
  invented (drop the inclusion). The last is decided on positive evidence -
  the symbol absent from the inclusion text *and* present in the exclusion
  text - not on absence from the inclusion text alone, which condemned every
  gene inferred from variant nomenclature: "H3 K27M-mutant diffuse glioma"
  names no H3 symbol, so a correct H3-3A requirement looked fabricated.
- `src/clinical_trials_gov.py` — diagnosis mapping picks Oncotree level_1
  nodes and then picks children within them, so a wrong level_1 removed the
  correct answer from the list the model was shown rather than merely making
  it less likely. Neuroblastoma sits under Peripheral Nervous System but
  arises in the adrenal medulla, so "Adrenal Gland" was the natural pick and
  its only children are adrenocortical adenoma, adrenocortical carcinoma and
  phaeochromocytoma: five of six neuroblastoma trials returned exactly that
  pair, silently. Terms named outright in `conditionsModule` are now read
  first and force their own branch into the second stage.
- `src/trial_data_helper.py` — `all_tumours` and `all_solid_tumours` matched
  only the bare broad terms, so "Pediatric Cancer" and "Childhood Cancer" were
  not recognised as basket trials and fell through to a hard mapping failure.
  Leading and trailing qualifiers are now peeled and both forms tested,
  additively, because stripping can destroy a match as easily as create one -
  "Malignant Neoplasm" is matched by an exact comparison that "Neoplasm"
  fails. 92 trials took the basket path before, 103 after. The same peeling
  serves the diagnosis seed, where ClinicalTrials.gov puts the qualifier after
  the diagnosis at least as often as before it ("Medulloblastoma Recurrent",
  "Neuroblastoma, Recurrent, Refractory").
- `src/clinical_trials_gov.py`, `src/trial_map_manager.py` — a trial with no
  determinable Oncotree diagnosis raised, and the whole trial was lost: its
  genomic criteria, its age bounds, everything. The failure modes are not
  symmetric. An over-broad trial costs a clinician minutes; a trial that is
  absent from MatchMiner is one no patient can be matched to and no reviewer
  can see is missing. It is now mapped without a diagnosis criterion, logged
  at ERROR, and written to `config.CTML_REVIEW_PATH` instead of the normal
  output, so it is visible and queued rather than discarded or published.
- `utils/ai_helper.py` — nine of eleven prompts asked for JSON in prose with
  no schema. A malformed answer was logged as a `JSONDecodeError` and replaced
  with an empty dict, so the whole response was discarded as though the model
  had found nothing, indistinguishable downstream from a trial with no
  diagnoses.

- `diagnoses_from_conditions` — tries `", NOS"` as a last candidate. Oncotree
  suffixes its catch-all nodes that way and registries do not, so
  "Low-grade Glioma", "Glioma", "Sarcoma" and "Round Cell Sarcoma" named nodes
  an exact match could not find. Tried last, after the plain and
  qualifier-stripped forms, so it fires only when nothing else matched -
  ordering is the guard, since first place would give "Medulloblastoma" both
  the exact node and its ", NOS" sibling. Across the corpus the seed now
  covers 356 of 924 trials rather than 326, and 611 terms rather than 556.
- `_basket_wildcards` in `src/clinical_trials_gov.py` — a trial is a basket
  only when its conditions name no specific Oncotree diagnosis. `all_tumours`
  and `all_solid_tumours` fire on any broad condition, and registries file a
  category header beside the real diagnoses often enough that this replaced a
  precise answer with `_SOLID_`: NCT04775485 lists "Advanced Solid Tumor"
  next to "Low-grade Glioma", NCT04897321 puts "Pediatric Solid Tumor" ahead
  of osteosarcoma, rhabdomyosarcoma, neuroblastoma, Ewing sarcoma and Wilms
  tumour. 31 of the 104 cached trials with a broad condition also name a
  specific one, and are no longer treated as baskets. The genuine kind -
  NCT02813135, whose only condition is "Pediatric Cancer" - is unaffected.
- `bench/curations.py` — NCT02813135 re-curated as `_SOLID_` + `_LIQUID_`.
  The key enumerated twelve paediatric tumours for a trial whose criterion is
  "a haematologic or solid tumor malignancy that has progressed despite
  standard therapy". A list is not a safer basket; it withholds the trial from
  every child whose tumour is not on it.

- `bench/curations.py` — NCT05009992 moved out of a hand-written YAML and
  re-curated. Its diagnosis held one Oncotree node where the trial names two:
  it enrols "diffuse midline glioma H3K27M mutant; WHO grade III and IV H3
  wildtype gliomas", and the H3-wildtype half is its own node. Its gene set
  stays empty and that is deliberate - H3K27M and cohort 5's
  BRAF/PDGFRA/FGFR1/NF1 requirement are both alternative cohorts, so the
  trial-level requirement is none.

- `map_age_numerical` — emits the trial's **upper** age bound as well as its
  lower one, one unit above the stated `maximumAge` because that field is in
  completed units: a participant whose maximum age is 17 years is 17 until the
  day they turn 18, so the eligible set is age < 18. `<=17` would drop every
  eligible 17-to-18-year-old, which in paediatric oncology is the AYA group.
  NCT02443831 pairs "24 Years" with "24 years or younger" and NCT03643276
  pairs "17 Years" with "age < 18 years (up to 17 years and 365 days)". `maximumAge` was read nowhere in the codebase, so every trial was
  open-ended at the top: NCT06776952 enrols patients aged 18 to 70 *days* and
  matched every child in the database. 613 of the 924 cached trials state a
  maximum and 56 cap below 18. Returns a list, and
  `convert_to_ctml_clinical_schema` emits the second bound as a sibling
  `clinical` node — two `age_numerical` keys cannot share one dict, and
  MatchMiner intersects sibling nodes, which is how a range is expressed.
  Verified against MatchMiner: `age_numerical` has no `allowed` list in
  `yaml_clinical_schema`, its query transformer accepts `<=`, `<`, `>=`, `>`
  and `==`, DFCI's own integration fixture `younger_than_18.json` curates
  `"<18"`, and each `clinical` dict becomes its own query node so two bounds
  on the same field do not collide.
- `bench/benchmark_map.py` — scores `age_numerical` instead of the trial-level
  `age` label. `facts()` had collected the bounds all along and nothing read
  them. The label is derived deterministically from `stdAges`, so scoring it
  compared a registry fact against a curator's judgement; 35 of 49 trials
  disagreed, always in the same direction. `<` and `<=` are normalised
  together because MatchMiner maps both to the same operator.
- `bench/build_reviewed.py`, `bench/curations.py` — the `age` label is no
  longer curated; it comes from `map_age_group` like every other field the
  scorer does not compare. 39 curated entries lost the kwarg and 9
  hand-written keys were realigned.
- `utils/oncotree.py` — `_parse_level_value` stripped the Oncotree code by
  splitting on the first `(`, which truncated the twenty nodes whose display
  name contains a parenthesis of its own and merged those sharing a prefix:
  the five `B-Lymphoblastic Leukemia/Lymphoma with t(...)` subtypes all
  became `B-Lymphoblastic Leukemia/Lymphoma with t`, and three `AML with
  t(...)` translocations became `AML with t`. The model was offered a name
  no patient record can carry, answered with it, and had the answer rejected
  by `utils/reference_validation`, which parses the same file with an
  end-anchored pattern. Both now use that pattern. Fifteen of the twenty are
  haematological — ETV6-RUNX1, TCF3-PBX1, BCR-ABL1, KMT2A-rearranged,
  RUNX1-RUNX1T1, CBFB-MYH11 — so the largest paediatric disease group was
  the worst affected. 18 nodes became reachable, 9 invalid strings are gone,
  and the 32 level_1 categories are unchanged. A test now asserts that every
  name offered to the model is one the validator accepts.

## Reference data

- `ref/genes.txt` — Kispi's 1,092-symbol paediatric list replaces the COSMIC
  Cancer Gene Census, resolved to 1,086 current HGNC symbols.
- `ref/synonym_to_gene_symbol.tsv` — regenerated from NCBI Gene. The previous
  table mapped H3, H4 and H5 to FGFR1, which current NCBI does not list.
- `ref/Census_gene_list.csv` — untracked. The COSMIC licence restricts
  redistribution and this fork is public. Nothing reads it at runtime.
- `ref/genes_kispi.txt` — the raw list as Kispi supplied it, kept so the
  normalisation to current HGNC stays auditable. The difference from
  `ref/genes.txt` is fifteen renames, and those are the only retired spellings
  the validator will rewrite.
- `ref/gene_synonym_addendum.tsv` — case variants NCBI stores only in upper
  case (`p53`, `p16`, `Ini1`), multi-gene aliases (`RAS`), and a `!` blocklist
  for aliases handled elsewhere (`PD-L1`, which has its own biomarker path).
- `ref/synonym_collisions.tsv` — aliases claimed by more than one gene,
  quarantined by `utils/build_gene_synonyms.py` rather than guessed at.

The seven files are read through one module. `utils/reference_validation`
owns every open: `_read_synonym_rows` applies the `!` blocklist once,
`gene_synonym_mapping()` serves the input side and `canonical_gene` the
output side. `TrialMapManager` and three tests each used to carry their own
copy of the loader, and the `!` convention was honoured in one of them and
silently ignored in the others. Paths now come from `config.GENE_LIST_FILE_PATH`,
`LEGACY_GENE_LIST_FILE_PATH`, `GENE_SYNONYM_FILE_PATH` and
`GENE_SYNONYM_ADDENDUM_FILE_PATH` rather than from string literals in six
files.

## Removed

- `utils/get_gene_synonym_mapping.py` — the one-time script that built the
  original synonym table from the COSMIC Census. `utils/build_gene_synonyms.py`
  replaced it, and it was the last runtime reader of `ref/Census_gene_list.csv`.
- `utils.aho_corasick.get_gene_list` and `TrialMapManager.get_gene_list` — the
  first was called only by its own test; the second was called three times per
  run and its result passed to `map_nct_to_ctml`/`map_ctis_to_ctml`, which
  never referenced the parameter. The `genes` argument is gone from both.
- `utils/schema.py` — declared `trial_genomic_json_schema` and was imported by
  `utils/ai_helper.py` without ever being referenced. Its two extra fields,
  `variant_classification` and `exon`, have been folded into the live
  `GENOMIC_CRITERIA_SCHEMA`; omitting them there had silently removed the
  model's ability to emit them at all, since llama.cpp builds its grammar from
  the declared properties.

## Tooling and documentation

- `bulk_convert_yaml_to_json.py` — rewritten as a CLI over `ctml/reviewed`
  instead of a script with a hardcoded list of NCT ids.
- `config.py` — Anthropic settings, Ollama context and prediction limits, a
  request timeout, `CTML_REVIEW_PATH` for trials that need a human before they
  are usable, the four `GENE_*` reference paths, and the model the cluster runs. `scripts/run_ollama_mapping.sh`
  reads the model from here, so this file is the single source of truth for it.
- `.gitignore` — untracks pulled trial data, logs, the COSMIC census, the NCBI
  harvest cache, and the transient `ctml/json` hand-off queue.
- `doc/nct_to_ctml_mapping_guide.md` — updated for this fork.
- `tests/test_reference_validation.py`, `tests/test_ai_schemas.py`,
  `tests/test_diagnosis_branch_floor.py` are new;
  `tests/test_match_criteria_mapper.py` gained cases for contradiction
  resolution and fabricated inclusions.

## Still carrying upstream assumptions

- `ref/local_trial_info.csv` holds ~97 CUHK/HKU/Korean institutional trials
  and is merged into `trial_status.csv`, so it mislabels trials with foreign
  PIs and protocol IDs. Needs replacing with Kispi data or emptying.
