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

### maximumAge is in completed units, and ~1 trial in 3 says otherwise

`map_age_numerical` emits `<=N+1` from the structured `maximumAge`, because
that field is in completed units: a participant whose maximum age is 17 years
is 17 until the day they turn 18, so the eligible set is age < 18. The
registry's own trials confirm the reading - NCT02443831 pairs "24 Years" with
"24 years or younger", NCT03643276 pairs "17 Years" with "age < 18 years (up
to 17 years and 365 days)". Emitting `<=17` would drop every eligible patient
between 17.0 and 17.99, which in paediatric oncology is the adolescent and
young adult group, not a rounding error.

Sponsors are not consistent about it. Reading the age sentence out of all 50
benchmark trials by hand, roughly two in three state an inclusive limit that
matches the completed-units reading, and **eleven state an exclusive one** -
NCT06528691 says "birth to age <3 years" against a structured "3 Years",
NCT02813135 says "Age < 18 years" against "18 Years", NCT06023641 says
"< 22 years (eligible for enrollment until 22nd birthday)" against "22 Years".
For those, `<=N+1` is a year too wide.

No arithmetic rule on the structured field fits both groups. The wider reading
was chosen deliberately: an over-broad trial costs a clinician the minute it
takes to reject it, while a narrow one silently withholds a trial from a
patient who qualifies. The fix that would settle it is reading the explicit
bound out of the eligibility prose and preferring it - see below, it is the
same gap.

The answer keys were re-curated against each trial's own age sentence rather
than against either rule, so the benchmark's age column measures this honestly:
expect about 0.76, with 11 of the 16 disagreements being exactly this.

**Addressed 2026-09-23** together with the next entry: the model now reads
both bounds from the inclusion text (`utils.ai_helper.get_age_bounds`), and
a structured maximum is narrowed to `<N` when the prose states an exclusive
bound at the same N (`utils/age_bounds.py`). Measured with the production
prompt on claude-haiku-4-5 over the 50 NCT keys: age F1 **0.763 -> 0.919**,
exact 34 -> 44, no trial worse. This costs one extra model call per
ClinicalTrials.gov trial.

What remains is judgement, not reading. Several neuroblastoma trials put
ages into their *risk definitions* ("Age 12-18 months with unfavourable
biology", "Age >= 547 days and INRG stage M"), and the keys and the model
draw the line between a risk definition and an enrolment bound differently
(NCT02559778, NCT04221035, NCT06172296). The structured minimum also stays
authoritative where the key followed the prose instead (NCT01704716:
structured 1 month, key 1 year).

### Age bounds stated only in prose are not mapped

*Addressed 2026-09-23 - see the entry above. NCT04625907 now gets `>=1` and
`<26` from its text.*

**Still open: site-dependent limits.** 2025-520982-39-00 (ALLTogether)
states "<18 years (for AIEOP-BFM), <22 years (for COG) and <46 years (for
ALLTogether sites)". The widest-range rule returns `<46`, the key says
`<=22`, and neither is Kispi's own limit. That limit is presumably `<18`, as
an AIEOP-BFM site. No trial-level rule gets this right; it needs a
per-site field or a curator.

`map_age_numerical` reads the structured `minimumAge` / `maximumAge` and
nothing else, so a trial that states its limits only in the eligibility text
gets no bound. `NCT04625907` carries no structured ages at all, while its
curated key holds `>=1` and `<=25` taken from the prose; `NCT02559778` states
18 months in the text and nothing structured. This is the bulk of the gap
between the benchmark's age F1 (~0.83) and 1.00, and it is visible now only
because that column scores the bounds rather than the trial-level label.

### Our OncoTree is newer than the table MatchMiner maps against

*Out of scope since 2026-09-23: the consumer is the flat index
(`utils/build_trial_index.py`) joined by Kispi's own genomics pipeline, not a
MatchMiner instance, and both sides of that join use `ref/oncotree_file.txt`.
Kept because it applies again the moment a MatchMiner instance does.*

`ref/oncotree_file.txt` is `oncotree_2025_10_03`, the current latest stable
(verified against the OncoTree API: 879 names, zero difference). MatchMiner
resolves `oncotree_primary_diagnosis` through an `oncotree_mapping.json` -
`external_file_mapping` in the matchengine does
`resource.setdefault(trial_value, trial_value)`, so a name in that file
expands to every descendant and a name absent from it falls back to an exact
string match.

The table shipped with DFCI's matchengine predates the 2021 WHO CNS5
restructuring, and the differences are in both directions:

    in ours, absent there    Diffuse Midline Glioma, H3 K27-Altered
                             Pediatric-Type Diffuse High-Grade Glioma
                             B-Lymphoblastic Leukemia/Lymphoma, NOS
    there, retired in ours   Anaplastic Astrocytoma
                             Diffuse Intrinsic Pontine Glioma

313 of our 879 nodes are absent from it, including 22 of the 87 diagnoses our
own answer keys use. Absent does not mean broken - the fallback is an exact
match - but it does mean matching is a string join between our vocabulary and
whatever vocabulary the patient records use, and nobody has checked that they
agree.

Two consequences. Emitting a *parent* is the cheap way to cover a population,
because a mapped parent expands (`Diffuse Glioma` to 13, `Rhabdomyosarcoma` to
6, `_SOLID_` to 561) - but only for names the receiving table knows. And the
benchmark cannot see any of this: a diagnosis scoring 1.00 against
`ctml/reviewed` matches nothing if the patient records spell it differently.
**Confirm the receiving instance's table before tuning the diagnosis path
further.**

One inherited hazard worth checking there: upstream shipped its own
`ref/oncotree_mapping.json` until commit `520826f` deleted it, and in that
file `_LIQUID_` mapped to an empty list - which the engine turns into
`{"$in": []}`, matching no patient at all.

### Stage 2 over-generates, and that is where the diagnosis score is

Measured on the 2026-09-15 run (llama3.3:70b, 50 trials): diagnosis **recall
0.775, precision 0.598**. Eleven trials emit **232 diagnoses against 39
curated** - 55 against 2, 45 against 12, 32 against 10, 28 against 4. The
model finds the right answers and buries them. This is now the largest single
lever in the project.

The mechanism is the size of the candidate list. Stage 2 is handed every child
of the chosen level_1 and asked which apply: 126 for CNS/Brain, 120 for
Lymphoid, 148-234 when a trial spans several branches. NCT04732065 is handed
all 126 CNS nodes and returns 28; its curated answer is 4.

**Two obvious fixes are already ruled out by measurement.**

Asking for less is not it - the prompt already says "Only include a diagnosis
if the condition or cancer type is explicitly stated in TrialInfo" and "Do not
infer diagnoses from drug names, treatment regimens, parent studies, or other
indirect clues". The model is not disobeying a vague instruction; it is being
generous over a 126-item list.

Dropping the model is not it either. Conditions-only, with no stage-2 call at
all, scores **0.529** against the run's 0.616. The model contributes about
0.09 of real recall. It needs constraining, not removing.

A deterministic text-support filter has a measured ceiling: only **67% of
curated diagnoses (98/147) appear literally in the trial's own text**, so a
hard "must be named" gate would discard a third of correct answers. The other
third are genuine inferences. Useful as a signal, not as a gate.

**What is worth trying, in order.**

1. *Shrink the candidate list.* Ask within the level_2 the conditions point
   at rather than all children of level_1 - "Diffuse Glioma" rather than the
   whole of CNS/Brain. The seed can supply the floor the same way it already
   does for level_1, so a wrong level_2 does not make the answer unreachable.
2. *Ask per condition, not per trial.* `get_child_level_diagnoses_from_condition`
   already works this way on the other path and is naturally bounded; the
   eligibility path asks once for the whole trial.
3. *Verify each returned term in a second pass*, the same shape as the genomic
   enrichment pass. Doubles the calls on the diagnosis path.

**Build the harness first.** None of these can be judged from a single run -
run-to-run variance on this benchmark exceeds the effect size of a single fix,
which has already misled us once. A replay harness that exercises only stage 1
and stage 2 over the 50 cached trials would cut the loop from ~100 minutes to
minutes and make an A/B honest. That is the first thing to build, not the
last.

### The benchmark cannot see which diagnosis actually matches a patient

This was filed for two days under "scoring decisions, not defects", on the
reasoning that `B-Lymphoblastic Leukemia/Lymphoma` and
`B-Lymphoblastic Leukemia/Lymphoma, NOS` are both valid Oncotree nodes and
choosing between them is curation policy. Checked against the running
MatchMiner instance on 2026-09-16, that was wrong.

    B-Lymphoblastic Leukemia/Lymphoma        expands to 8 terms, incl. the NOS leaf
    B-Lymphoblastic Leukemia/Lymphoma, NOS   expands to 1: itself

Patients are coded with the parent. The instance holds the controlled pair
already: `2023-509392-17-00` names the parent and matched its B-ALL patient,
`NCT03643276` named the leaf and matched nothing - same patient, same engine,
same run. Seven of the fifty keys said ", NOS", so seven trials were invisible
to a patient with the commonest childhood cancer. All seven now name the
parent, and the dry run over the live mapping goes from 23 of 55 trials
reaching a patient to 30.

The general problem stands and is larger than those seven. `prf()` compares
strings, so it scores a diagnosis that matches every B-ALL patient exactly the
same as one that matches none - and on 2026-09-15 it scored the pipeline's
*correct* parent answers as spurious on NCT05366218 and NCT05748171, marking
them 0.0. **The benchmark is blind to the only property that matters.**

**Addressed 2026-09-23**, without the deployment file: MatchMiner is no
longer the consumer, so expansion runs through our own `ref/oncotree_file.txt`
(`utils.build_trial_index.diagnosis_population`). The benchmark now reports
`pop_p` / `pop_r` beside the name scores - see `bench/README.md`. What remains
open is the coding assumption it rests on: patients are coded at the most
specific node, which means every node except the 20 parents that have a
", NOS" child. That is what Kispi's pipeline was stated to do, not something
measured. And every codable node counts once, so a rare subtype weighs as much
as B-ALL. Weighting by the lab's own diagnosis frequencies would fix that, and
needs a list of the codes the lab has actually assigned.

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

The population metric puts a size on it (2026-09-23, `--conditions-only`):
NCT02332668 reaches **2%** of the patients its key does, NCT07440290 **3%**.
By name both scored 0.0, the same as a wrong answer; by population they are
the two worst recall failures in the set. The opposite shape exists too:
NCT03838042 and NCT05580562 get `_SOLID_` where the key names specific
tumours, so precision is 0.02 and 0.04. Both are over-broad rather than
missing, which costs less.

**Addressed 2026-09-23** for the first shape: `seed_and_map_diagnosis` now
adds the wildcards whenever the basket rule fires, as a union with the named
terms. Recall on NCT02332668 went 0.02 -> 0.75 and on NCT07440290 0.03 -> 1.00,
with no other benchmark trial changed. Across the corpus the change touches
12 of 924 ClinicalTrials.gov trials, and the inclusion criteria of all 12
were read: each describes a basket. NCT02332668 stays short of 1.00 because
its rule yields `_SOLID_` alone, and its "lymphoma" arm is covered only by
the Classical Hodgkin Lymphoma it names.

### The mapper drops protein changes the index could now check

`match_criteria_mapper._clean_protein_change_fields` keeps a protein change
only if it matches one of three one-letter patterns: substitution,
deletion range, insertion range. Anything else is removed silently: nonsense
(`p.R213*`), three-letter code, single-residue deletions, duplications,
delins, frameshifts. The criterion is not lost; it becomes gene-level, which
is over-broad, the tolerable direction. But a trial that names a specific
variant then matches every variant in the gene. `utils/protein_change.py`
handles all of those forms and checks them against the reference, so the
mapper could use it instead of the patterns and send failures to review.
Not changed yet: the curated corpus has no example, and the change moves
output on the next full mapping run.

### Off-panel fusion partners are dropped, and that is correct

A scan of all 924 cached trials against the Cancer Gene Census finds only ten
off-panel symbols anywhere in their eligibility text, and just five used as
molecular criteria: `RUNX1T1`, `IGH`, `SET`, `ZC3H7B` and `USP9X`. The
validator drops all five. Every one is a fusion partner, and adding them was
considered and rejected.

(The other five - `HLA-A`, `CYP2C8`, `CD28`, `TNC`, `RNF43`/`RRAS2` - are
donor matching, a drug-interaction rule and a CAR construct. None belongs on
a somatic panel.)

CTML expresses a fusion as one `hugo_symbol` plus `Structural Variation`, with
the partners under `or` - see `ctml/reviewed/2025-520982-39-00.yaml`, where
BCR-ABL1 is four OR'd nodes. So a criterion matches if *either* partner is on
the panel, and for all five the other half already is: RUNX1T1/RUNX1,
IGH/CRLF2, SET/NUP214, ZC3H7B/BCOR, USP9X/DDX3X.

NCT05985161 is the clearest case: BCOR-ITD, BCOR-CCNB3, BCOR-MAML3 and
ZC3H7B-BCOR all carry BCOR. NCT05745714 names P2RY8-CRLF2, EPOR, STAT5B and
DNM2 beside its USP9X clause, and all four of those are on the panel.

Adding them would therefore add an OR branch that can never fire, because
`ref/genes.txt` is Kispi's panel and a gene absent from it is a gene the lab
does not report. The drop is noisy in the log and costs nothing. Revisit only
if the panel itself changes.

Not the same question as whether the *alias* table should widen. `HIST1H3A` and
`HIST2H3C` are dropped too, but the synonym table resolves them to H3C1 and
H3C14, which are on the panel - a correct answer thrown away over spelling.
See "The rewrite set is narrower than it needs to be" below.

## Unmeasured guesses

### The 400-value enum cap
`utils/ai_helper._MAX_ENUM_VALUES` drops the enum from a schema above 400
candidates, on the reasoning that llama.cpp compiles `format` into a grammar
and hundreds of alternatives are slow to build. The threshold has never been
measured on a GPU. With the branch floor now unioning several Oncotree
branches, the candidate list can approach it. If per-trial time jumps, look
here first.

## Scoring decisions, not defects

### Run-to-run variance exceeds most single fixes
Measured 2026-09-14: the reference-validation change did exactly what was
predicted on the two trials it touched, and the overall dx F1 still fell,
because two neuroblastoma trials happened to flip branch in the same run. A
single run cannot evidence a change worth a few points. Compare per-trial, or
repeat runs.

## Answer key

Six keys have now been corrected after a run log exposed them, all of them
mine. The pattern is worth naming: every one was written from a truncated
view of a long trial, and and all but one were caught by the pipeline
producing *more* than the key held rather than less. A key that is too small
is invisible until something disagrees with it - and NCT02813135 shows the
same blindness in the other direction, where enumerating twelve tumours read
as diligence and was actually a narrower trial than the protocol describes.

- **NCT06239272** (fixed 2026-09-12). 42 conditions - every
  non-rhabdomyosarcoma soft tissue sarcoma subtype - against a key holding 6.
  18 of the 42 resolve to Oncotree; the union with the old key is 20.

- **NCT02813135** (fixed 2026-09-15). The first key that was too *specific*
  rather than too small: twelve enumerated paediatric tumours for ESMART,
  whose sole condition is "Pediatric Cancer" and whose criterion is "a
  haematologic or solid tumor malignancy that has progressed despite standard
  therapy". Now `_SOLID_` + `_LIQUID_`. The pipeline had it right and the key
  scored it 0.0.

- **NCT05009992** (fixed 2026-09-15), after a run log made it look
  under-curated on genes. It was not. H3K27M reads like a requirement and is
  not one: the inclusions admit "diffuse midline glioma H3K27M mutant; WHO
  grade III and IV H3 wildtype gliomas" in one sentence, and cohort 5's
  BRAF/PDGFRA/FGFR1/NF1 requirement applies to cohort 5 alone. Both are
  alternative cohorts, so the trial-level genomic requirement is none and the
  empty gene set was right. The *diagnosis* was wrong, though - one node where
  the trial names two, missing the H3-wildtype high-grade gliomas it enrols
  beside the H3 K27-altered ones.

## Coverage

- `src/ctis.py` has never been run against a real model. `bench/benchmark_map.py`
  reads `cache/nct` only, so every benchmark to date has been NCT-only, and the
  five curated CTIS trials in `ctml/reviewed` are never scored.
- No tests for `src/clinical_trials_gov.py` (854 lines),
  `utils/llm_platforms.py` (432) or `src/ctis.py` (250) beyond what
  `tests/test_diagnosis_branch_floor.py` covers.

### The rewrite set is narrower than it needs to be

`canonical_gene` rewrites a retired symbol only if it is one of the fifteen
renames between `ref/genes.txt` and `ref/genes_kispi.txt`. That set exists
because the full synonym table maps `ALL` to BCR, `AT` to BTK, `ARF` to
CDKN2A and `H3` to H3C14, and in a paediatric pipeline "ALL" is a disease
name in nearly every trial.

The cost is real: `HIST1H3A` -> H3C1 and `HIST2H3C` -> H3C14 are panel genes
the validator throws away over spelling, even though the synonym table holds
both mappings. `HIST1H3B` and `HIST1H3C` *are* rewritten, purely because
`genes_kispi.txt` happened to list those two spellings and not the others -
which is the whole argument that the set is drawn on the wrong criterion. The
DMG trials are worst hit, since the WHO literature spelling of the histone
genes is the retired one.

Widening would not rescue everything. `cCBL` is in neither table; it is a
lowercase-prefix variant of CBL that only a normalisation step would catch.

Every dangerous alias is three characters or fewer. Measured over the synonym
table: 4,885 unambiguous aliases point at a panel gene, a >=4-character floor
keeps 4,301 of them, and none of the 447 four-letter purely alphabetic
aliases collides with a common English or clinical word. Unmeasured is what
the widened set would do to a real run, which is why this is written down
rather than applied.

One dependency: widening this makes the addendum's `!` blocklist load-bearing
on the validation side for the first time. `!PD-L1` would otherwise start
resolving PD-L1 to CD274 and bypass the dedicated biomarker path. The
blocklist is now applied in `_read_synonym_rows`, so the guard is in place,
but it is the thing to check first.

## Cleanup

- **`get_arm_criteria_mapping_prompt` was the last schema-less prompt** and is
  now schema'd, but the arm labels it returns are still matched back to CTML
  arms by string equality downstream. The enum makes the label verbatim, so
  this should hold; it has not been exercised on a trial with awkward labels.
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
- **README documents neither CTIS nor the benchmark**, though `main.py` has
  `--source {nct,ctis,all}` and `bench/` is a full harness.
- **`doc/nct_to_ctml_mapping_guide.md`** does not describe the two-stage
  level_1 mapping or the branch floor.
- **`config.py` carries ~24 commented-out `LLM_AI_MODEL` lines**, which is why
  the live setting drifted out of step with the cluster unnoticed.
- **Possibly dead, unconfirmed**: `bulk_convert_yaml_to_json.py` and
  `src/get_all_intervention_types.py` have no importers and may be standalone
  scripts still in use. `rag/llamaindex/` and `rag/simple/` are upstream
  notebooks unconnected to this pipeline. `yaml/` contains one tracked file:
  `.DS_Store`.

## Inherited from upstream

- `src/trial_pull_manager.py:329` — trials in `trial_status.csv` that the API
  stops returning are unhandled (upstream `TODO`).
- `utils/ai_helper.get_arm_criteria_mapping_prompt` is the one prompt still
  sent without a JSON schema, carrying an explicit "intentionally ... for now"
  comment. It has the same silent-discard exposure as the nine that were fixed.
