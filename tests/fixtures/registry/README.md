# Registry fixtures

Frozen ClinicalTrials.gov records (API v2 JSON, as `main.py pull` caches
them), so the tests and the benchmark regression check run without
`cache/`, which is not in git.

- `nct/`: the 50 NCT trials curated in `ctml/reviewed/`, plus `NCT06776952`,
  which `tests/test_age_bounds.py` reads. Copied from `cache/nct` on
  2026-09-28; the newest record was last updated on the registry on
  2026-09-25.
- **Source:** [ClinicalTrials.gov](https://clinicaltrials.gov), U.S.
  National Library of Medicine. ClinicalTrials.gov content is in the public
  domain; the source is acknowledged here as NLM asks.
- **CTIS:** no fixtures yet. EMA's legal notice allows reproduction with
  acknowledgement but excludes third-party content, and CTIS records are
  submitted by sponsors. The 6 curated CTIS trials, and the tests that need
  them, stay out of CI until that is settled.

These are frozen on purpose: a regression check needs inputs that do not
move. CI copies `nct/` into `cache/nct`. `bench/baseline_conditions_nct.json`
is computed from these files; refresh both together (see
`bench/conditions_baseline.py`).
