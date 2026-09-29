# Reference data

The files in `ref/`, where each comes from, and how they are checked. Moved from the README on 2026-09-28.

| File | What it is |
|---|---|
| `ref/SOURCES.tsv` | where every other file here comes from: kind, source, version, date retrieved and, for files that come from outside, the pinned SHA-256. See below. |
| `ref/oncotree_file.txt` | Oncotree tab-delimited export, `oncotree_2025_10_03` (879 names). Fetched with `python -m utils.verify_refs --fetch-oncotree <version>`. A test pins the count and the documented version. |
| `ref/genes.txt` | Kispi's paediatric gene panel, 1,086 current HGNC symbols. The accept-list for `hugo_symbol`. |
| `ref/genes_kispi.txt` | the panel as Kispi supplied it (1,092 symbols); its difference from `genes.txt` defines which retired spellings may be rewritten. |
| `ref/synonym_to_gene_symbol.tsv` | gene aliases from NCBI Gene, rebuilt by `utils/build_gene_synonyms.py`. |
| `ref/gene_synonym_addendum.tsv` | case variants, multi-gene aliases, and a `!` blocklist. |
| `ref/synonym_collisions.tsv` | aliases claimed by more than one gene, quarantined rather than guessed. |
| `ref/diagnosis_synonyms.tsv` | curated registry disease spellings that folding cannot reach, each with its reason. |
| `ref/mane_genes.tsv` | symbol and HGNC id of every MANE Select v1.5 gene (19,364); validates fusion partners. Written by the same builder. |
| `ref/diagnosis_text_terms.tsv` | how eligibility text names an Oncotree diagnosis, for text matching only (`src/text_rules.Reference.dx_terms`): the exclusion-only check and the review sheets. |
| `ref/gene_rewrite_exclusions.tsv` | aliases `canonical_gene` must never rewrite to a panel gene although the synonym table maps them to one (JMML, CHOP, PD-1). |
| `ref/translocation_fusions.tsv` | cytogenetic rearrangement to the gene pair it creates (`t(9;22)` to BCR::ABL1), each row with its reason; read by `utils/translocations.py`. |
| `ref/local_trial_info.csv` | local protocol ids and PIs per trial; header-only for now, and the only route by which a closed trial is pulled. |
| `ref/scope_overrides.tsv` | per-trial overrides of the map-time oncology scope filter, each with its reason. |
| `ref/mane_select_proteins.tsv` | MANE Select GRCh38 v1.5 protein sequences for the panel and every histone H3 gene, with RefSeq and Ensembl accessions; the header records each source file's SHA-256. Rebuilt per MANE release with `python -m utils.build_protein_reference --release 1.5`. |

`ref/Census_gene_list.csv` (COSMIC) is untracked because its licence restricts
redistribution; nothing reads it at runtime.

`python -m utils.verify_refs` checks `ref/` against `ref/SOURCES.tsv`, in CI
on every push and in `tests/test_reference_sources.py`. Every file must be
listed. Files that come from outside (fetched, built or supplied) are pinned
by SHA-256, so one replaced without its fetch or build step fails. After a
deliberate rebuild, re-pin it in the same commit with
`python -m utils.verify_refs --update <file>`. Curated files are not pinned;
git records their edits. `--online` compares `ref/oncotree_file.txt` with the
Oncotree API. The API does not serve a version byte for byte the same over
time: it now gives `oncotree_2025_10_03` a different layout and two extra
cross-reference codes for SRCCR. So only a difference in the tree fails;
metadata differences are shown as notes. GitHub runs the online check weekly.
