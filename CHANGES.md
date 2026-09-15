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
  Leading qualifiers are now peeled and both forms tested, additively, because
  stripping can destroy a match as easily as create one - "Malignant Neoplasm"
  is matched by an exact comparison that "Neoplasm" fails. 92 trials took the
  basket path before, 103 after.
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

## Removed

- `utils/schema.py` — declared `trial_genomic_json_schema` and was imported by
  `utils/ai_helper.py` without ever being referenced. Its two extra fields,
  `variant_classification` and `exon`, have been folded into the live
  `GENOMIC_CRITERIA_SCHEMA`; omitting them there had silently removed the
  model's ability to emit them at all, since llama.cpp builds its grammar from
  the declared properties.

## Tooling and documentation

- `bulk_convert_yaml_to_json.py` — rewritten as a CLI over `ctml/reviewed`
  instead of a script with a hardcoded list of NCT ids.
- `utils/get_gene_synonym_mapping.py` — unchanged in behaviour, documented as
  superseded by `utils/build_gene_synonyms.py` and as requiring a COSMIC
  download that is no longer tracked.
- `config.py` — Anthropic settings, Ollama context and prediction limits, a
  request timeout, `CTML_REVIEW_PATH` for trials that need a human before they
  are usable, and the model the cluster runs. `scripts/run_ollama_mapping.sh`
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
