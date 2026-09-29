"""
Mapping logic shared by both registries (improvement plan step 11, phase 2):
what works on criteria text and condition lists rather than on a registry's
document. src/clinical_trials_gov.py and src/ctis.py read their own documents
and call these.

- diagnosis: conditions as a floor, the two-stage Oncotree mapping, baskets
- genomic: genomic criteria from eligibility text, normalised and enriched
- biomarkers: HER2/ER/PR, PD-L1, MMR/MS and disease status from text
"""
