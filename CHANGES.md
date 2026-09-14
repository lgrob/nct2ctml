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
  that matches zero patients. Now detected and resolved.

## Reference data

- `ref/genes.txt` — Kispi's 1,092-symbol paediatric list replaces the COSMIC
  Cancer Gene Census, resolved to 1,086 current HGNC symbols.
- `ref/synonym_to_gene_symbol.tsv` — regenerated from NCBI Gene. The previous
  table mapped H3, H4 and H5 to FGFR1, which current NCBI does not list.
- `ref/Census_gene_list.csv` — untracked. The COSMIC licence restricts
  redistribution and this fork is public. Nothing reads it at runtime.

## Still carrying upstream assumptions

- `ref/local_trial_info.csv` holds ~97 CUHK/HKU/Korean institutional trials
  and is merged into `trial_status.csv`, so it mislabels trials with foreign
  PIs and protocol IDs. Needs replacing with Kispi data or emptying.
