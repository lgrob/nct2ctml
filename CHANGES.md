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

- `get_arm_criteria_mapping` — now sends a JSON schema, the last prompt that
  did not. It emits the largest nested object of any prompt and produced
  invalid JSON on the cluster (a parse failure at character 6057, well under
  the output cap, so malformed rather than truncated); NCT05745714 lost all
  twelve of its genomic criteria to it, silently, because `parse_response`
  returns `{}`. `arm_label` is an enum over the labels actually present, which
  also enforces in the grammar what the prompt only asked for in prose.
- Every `parse_response` names the trial when the model returns invalid JSON.
  The old message said only "Unexpected response format", so a run log could
  not say which trial had just lost a criterion. The identifier is threaded
  through all twelve `parse_ai_response` call sites.
- `expression_only_genes` in `src/trial_config.py`, applied by
  `filter_genomic_criteria` — CD19, CD22, CD274, CTAG1B and the HLA loci never
  become `genomic` blocks. Their criteria are about protein expression measured
  by flow or IHC, while MatchMiner's genomic path matches a sequencing report,
  so "CD19+ and CD22+ acute lymphoblastic leukaemia" became a required CD19
  mutation and a trial that matches nobody. Two trials in one 50-trial
  benchmark. Deliberately narrow: CD74 is excluded from the list despite being
  a false positive, because it forms real fusions a trial can require.
- `config.CTML_REVIEW_PATH` is `ctml/needs-review`, not `ctml/pending`. The
  README gives `ctml/pending` to hand-authored CTML for local trials, so the
  two review queues were sharing a directory and a reviewer could not tell a
  colleague's draft from machine output that failed to find a diagnosis.
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
  tumour. The genuine kind - NCT02813135, whose only condition is "Pediatric
  Cancer" - is unaffected. A trial registering **two or more** umbrella terms
  is a basket even when it also names diagnoses: a registry lists one umbrella
  as a header, so several different ways of saying "any malignancy" describe
  an unrestricted population. NCT07440290 registers "Malignant Neoplasm",
  "Cancer" and "Solid Tumour" among twenty conditions, and reading its two
  resolvable ones as the answer produced 55 diagnoses against a curated
  `_SOLID_` + `_LIQUID_`.
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

- Seven answer keys named `B-Lymphoblastic Leukemia/Lymphoma, NOS` where they
  should name the parent, `B-Lymphoblastic Leukemia/Lymphoma`. Checked against
  the running MatchMiner instance: the parent expands to eight terms including
  the NOS leaf, the leaf expands only to itself, and patients are coded with
  the parent — so those seven trials were invisible to a B-ALL patient. The
  instance held the proof already, in a pair of loaded trials differing only
  in that term, one matching and one not.

## Defect fixed: diagnosis matching lost to punctuation

`utils/reference_validation.canonical_diagnosis` matched Oncotree display
names exactly, by code, or case-insensitively, and nothing else. Registries
do not write what Oncotree writes, so the difference of a hyphen, an
apostrophe or a British spelling dropped the diagnosis and left it to the
LLM — which then had to pick a branch of a tree it could not see, the step
that puts neuroblastoma under Adrenal Gland
(see the two-stage funnel in `src/clinical_trials_gov.py`).

Real condition strings that returned nothing: `High Grade Glioma`
(NCT04655404), `Anaplastic Kidney Wilms Tumor` (NCT04322318),
`Acute Lymphoblastic Leukemia` (NCT02443831), `Diffuse Intrinsic Pontine
Glioma` (NCT05009992), `Stage I Testicular Seminoma AJCC v6 and v7`
(NCT03067181).

Three changes, all deterministic and offline:

- `_fold()` — a comparison key ignoring case, apostrophes, hyphens, slashes
  and British spelling. Commas survive, because Oncotree uses them to carry
  meaning (`Glioma, NOS` is not `Glioma`). British spellings matter here
  because the CTIS half of the corpus is European. All 879 display names fold
  to 879 distinct keys, so folding merges nothing the tree distinguishes; a
  test asserts this so a future Oncotree release cannot break it quietly.
- `ref/diagnosis_synonyms.tsv` — the curated aliases folding cannot reach.
- wider qualifier vocabulary — `Stage IIIB` (substage letters), `AJCC v6 and
  v7` (a staging-manual citation, not a diagnosis), bare trailing `Relapse`,
  and `untreated` / `unresectable` / `extracranial` / `extragonadal`.

Lookup order runs from most to least literal: exact, code, case-insensitive,
folded, then alias. Folding precedes the alias table so no hand-edited entry
can shadow a real Oncotree name.

Measured on the 50-trial curated key, conditions only, no LLM and no network:
diagnosis F1 **0.496 → 0.684** (precision 0.650 → 0.859, recall 0.436 →
0.617), 12 → 19 trials exactly right. That is above the 0.663 the full
two-stage LLM pipeline scored on 2026-09-15, at zero tokens and with no
run-to-run variance. Across the 924 cached trials, those resolvable from
conditions alone rise from 356 (39%) to 478 (52%).

The remaining gap is not a naming problem: it is the `_SOLID_`/`_LIQUID_`
basket heuristic, and trials like NCT03838042 whose conditions are only
`CNS Tumor, Solid Tumor` and whose diagnoses live in the eligibility text.

Two external vocabulary sources were tested and rejected, both because they
restate `conditionsModule` rather than adding to it. NCBI MeSH via E-utilities
resolves only terms that already match exactly, and misses every failing case
above — MeSH keeps DIPG as current, collapses `High Grade Glioma` to `Glioma`,
and does not split ALL by lineage; its fuzzy search also reaches Retinoblastoma
from "Neuroblastoma". `derivedSection.conditionBrowseModule`, which CT.gov
derives algorithmically from the same conditions, measured +0.006 F1 with
precision slightly down: one correct addition against three wrong ones.

## Defect fixed: CTIS never got the diagnosis safeguards

`src/ctis.py` called `map_eligibility_criteria_to_oncotree_term` directly with
no `seed_terms`, so the 331 cached CTIS trials — a quarter of the corpus — had
no deterministic floor from their own conditions, no branch forcing (the fix
that stops a wrong level_1 making the right diagnosis unreachable), no
`_SOLID_`/`_LIQUID_` basket detection, and no warning when the model dropped a
diagnosis the trial names outright. 61 of the 331 resolve from conditions
alone and every one was being left to the model.

Worse, `trial_map_manager.map_single_ctis_trial` saved straight to the output
directory instead of calling `_destination_for`, so a CTIS trial whose
diagnosis could not be determined bypassed the review queue and reached
MatchMiner, where it matches every patient in the database. The safety net was
only ever wired to the ClinicalTrials.gov path.

The shared logic is now `clinical_trials_gov.seed_and_map_diagnosis`, used by
both registries; only the fallback when it returns nothing differs, since CTIS
registers neither keywords nor a separate title. `_basket_wildcards` gained a
public name so CTIS need not reach for a private one.

## Defect fixed: inferred ", NOS" leaves matched almost nobody

`diagnoses_from_conditions` appends ", NOS" as a last-resort candidate, because
Oncotree suffixes its catch-all nodes that way and registries do not. But
MatchMiner expands a diagnosis to its descendants before querying, and a leaf
expands to itself alone. Verified against the deployed `oncotree_mapping.json`
on 2026-09-21: `Glioma, NOS` reaches **1** patient code where its parent
`Diffuse Glioma` reaches **24**. NCT05580562, whose conditions are
`['H3 K27M', 'Glioma']` and whose curated diagnosis is
`Diffuse Midline Glioma, H3 K27-Altered`, enrolled against a term that matched
nobody — not even the DMG patient — and the benchmark scored it correct,
because it compares strings and the deployment expands them.

An inferred leaf is now replaced by its parent, under two guards:

- climbing stops below level_1, so `Sarcoma, NOS` keeps its leaf rather than
  becoming the whole `Soft Tissue` root — which would enrol every soft-tissue
  tumour and still miss the bone sarcomas a sarcoma trial means;
- the parent must keep every word the leaf states, so `High-Grade Glioma, NOS`
  is not widened into `Diffuse Glioma` (which includes low-grade entities) and
  `Low-Grade Glioma, NOS` is not widened into `Encapsulated Glioma`.

Across the tree that widens the 8 true catch-alls — including
`B-Lymphoblastic Leukemia/Lymphoma, NOS`, the parent-beats-NOS case already
confirmed against two loaded MatchMiner trials — and leaves the 20
qualifier-bearing leaves alone, logged for a curator. A trial that writes
", NOS" itself is respected; only the suffix this code adds is widened.

Measured on the 50-trial key, scored through the deployed mapping: recall
0.672 → **0.692**, precision 0.890 → **0.879**, F1 flat. The aggregate does
not capture the point — the justification is the asymmetry this repo already
states, that an over-broad trial costs a clinician minutes while a missing one
can cost a patient a trial they were eligible for. Note that string-equality
scoring cannot see this trade at all, which is the argument for scoring
`bench/benchmark_map.py` through `oncotree_mapping.json`.

`utils/oncotree.get_lineage()` provides the parent, level_1 and descendant
relations. It computes expansion from `ref/oncotree_file.txt` rather than
reading the deployed file, so mapping stays independent of a running
MatchMiner; the two agree on 852 of 861 shared names, and all nine differences
are nodes our newer Oncotree has and the deployed table does not.

## New capability: a flat query index for downstream pipelines

`utils/build_trial_index.py` turns the curated CTML into three TSVs plus a
manifest, for a Nextflow pipeline that matches samples against trials without
MatchMiner.

CTML is a nested boolean tree, and "does this tree evaluate true for sample X"
is not expressible as a query over nested JSON - so every consumer would have
to implement a tree evaluator, which is the work MatchMiner's matchengine used
to do. The index flattens the expensive, semantics-heavy dimension once, at
build time, where it is tested:

    trials.tsv           one row per trial: phase, status, and the numeric age
                         window parsed out of the match tree, with the
                         inclusive/exclusive distinction kept ("<18" and
                         "<=18" differ by a year of patients). The trial-level
                         `age` label is carried for display only - it matches
                         no patient field.
    trial_diagnosis.tsv  one row per (trial, arm, Oncotree code), with the
                         diagnosis subtree already expanded.
    trial_genomic.tsv    one row per (trial, arm, gene), exclusions flagged
                         rather than dropped.
    manifest.json        row counts and SHA-256 of every output and of the
                         Oncotree file it was built against.

A consumer therefore needs no knowledge of CTML, of the Oncotree hierarchy or
of MatchMiner's wildcards: `_SOLID_` and `_LIQUID_` are expanded at build time,
and both the Oncotree code and the display name are emitted so a join can use
whichever the sample map carries. Prefer the code - it is stable across
releases where display names are not, `H3 K27M-Mutant` having become
`H3 K27-Altered`.

**The index is screening, not decisive.** Rows are a union of everything a
trial could match; the CTML file remains the authority on whether it does.
Exclusions and mixed and/or nesting do not denormalise losslessly, and a flat
table that claims to be authoritative is how it starts quietly disagreeing
with its source. `source_term` keeps the term the curator actually wrote, so a
screening hit can be explained back to the file rather than to an expanded
code.

Measured on the 55 curated trials: 3,975 diagnosis rows, 276 KB, and a full
scan for one diagnosis takes about a millisecond. Extrapolated to the whole
1,256-trial corpus that is roughly 88,000 rows and 3.4 MB - a lookup table, not
a data warehouse, so a database server would add a service dependency and buy
nothing. A single immutable file is also the better Nextflow input: it is
content-hashable, so `-resume` works, and it needs nothing standing up inside
a container.

The build is deterministic - identical inputs give byte-identical outputs - so
the manifest checksum identifies exactly which trial set produced a given
report. That property is worth keeping if any of this falls under the IVD:
a mutable database cannot answer "what would this have returned in March"
without separate audit machinery. `index/` is gitignored, on the assumption
that it is regenerated; if a report ever cites it, ship it as a versioned
release artefact with its manifest instead.

## Reference data

- `ref/oncotree_file.txt` — the tab-delimited export from
  <https://oncotree.mskcc.org>, dropped in by hand; no script fetches it.
  Upstream commit `520826f` updated it to **`oncotree_2025_10_03`** and the
  documentation was not updated with it, so `README.md`,
  `doc/nct_to_ctml_mapping_guide.md` and `doc/trial_creation_guide.md` told
  reviewers to verify diagnoses against `oncotree_2021_11_02` for the next
  three months. Verified against the OncoTree API: 879 names, zero difference
  from the 2025_10_03 release. A test pins the count and the documented
  version together.


- `ref/diagnosis_synonyms.tsv` — new. Registry disease spellings that no
  string transform can reach, mapped to Oncotree display names: lineage
  decisions (`Acute Lymphoblastic Leukemia` names no lineage, Oncotree has
  only B- and T- nodes), WHO CNS5 reclassifications (`Diffuse Intrinsic
  Pontine Glioma` is retired, its successor is `Diffuse Midline Glioma,
  H3 K27-Altered`) and NCI/COG house style (`Stage II Kidney Wilms Tumor`).
  Fifteen rows, each with its reason in a third column, because these are
  clinical judgements a curator must be able to challenge. Deliberately
  excludes the bare abbreviation `ALL` — three-character aliases are how the
  gene table went wrong. Rows whose target is not an Oncotree node, or whose
  alias already resolves without the table, are dropped at load time with a
  warning, so the file cannot silently rot as Oncotree moves.

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

## Backend: Claude Haiku 4.5 through the Anthropic API

Decided 2026-09-24 (roadmap D1). `config.py` now selects `Anthropic` with
`claude-haiku-4-5-20251001`, pinned to the dated snapshot so a run can be
reproduced. Every prompt measurement since 2026-09-23 was made on it, and it
is the cheapest current Claude model.

The platform as written would have failed on the first call. It always sent
`thinking: adaptive` and `output_config.effort`, and Haiku 4.5 supports
neither. It also sent schemas as `output_config.format`, a path its own
comment called untested. `AnthropicPlatform` now:

- sends thinking and effort only when `config.ANTHROPIC_THINKING` /
  `ANTHROPIC_EFFORT` ask for them, and refuses either with Haiku 4.5 before
  any call is made;
- runs at `ANTHROPIC_TEMPERATURE` (0) when thinking is off;
- enforces a prompt's schema through a forced tool call whose input wraps
  it as `{"result": ...}` (several prompts return a top-level array, and a
  tool input must be an object). This is the request shape all the Haiku
  measurements used, so production and benchmark now send the same request.

`scripts/run_ollama_mapping.sh` refuses to run unless `LLM_PLATFORM` is
`Ollama`, since it reads the model id from `config.py`.
`tests/test_anthropic_platform.py` covers the request body and the reply
parsing offline. Not yet done: a live call through this code path (roadmap
0.4).

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

## Still carrying upstream assumptions

- `get_nct_local_status` still describes itself as recruitment in Hong Kong,
  and `src/ctml_schema.py` still carries MatchMiner-only fields
  (`management_group_list`, `oncology_group_list`, `program_area_list`) with
  placeholder values.
