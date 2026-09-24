# Benchmarking the automated mapping

`ctml/reviewed/NCT*.yaml` are hand-curated. They are the answer key. This
harness runs the pipeline over the same trials and scores the result, so the
question "can the LLM curate CTML?" is settled with numbers rather than
impressions.

50 trials, spanning paediatric leukaemia, lymphoma, CNS tumours,
neuroblastoma, bone and soft-tissue sarcoma, renal, liver, germ cell,
retinoblastoma, histiocytosis and tumour-agnostic baskets. 24 of the 50 carry
a genomic criterion; the other 26 deliberately do not, because the commonest
way to get a trial wrong is to invent one.

## Where the answers come from

Each answer is written by hand in `bench/curations.py` after reading that
trial's own eligibility text, and `bench/build_reviewed.py` combines it with
the pipeline's deterministic, non-LLM mapping of the cached record (titles,
arms, drugs - none of which is scored):

    ./.venv/bin/python -m bench.build_reviewed --check   # validate terms only
    ./.venv/bin/python -m bench.build_reviewed           # rewrite the key

Every curated Oncotree term and HUGO symbol is checked against
`ref/oncotree_file.txt` and `ref/genes.txt` before a file is written. A typo in
the answer key is worse than a typo in the output: it marks a correct answer
wrong forever, silently.

Two rules decide most of the hard cases:

- **Alternative cohorts are not requirements.** If a trial enrols patients both
  with and without an alteration, the net genomic requirement is none. Writing
  it as a requirement produces a trial that matches nobody.
- **Stratification is not eligibility.** A biomarker that only assigns a risk
  group or an arm, while every group enrols, is not a match criterion. The
  clearest example in the set is NCT06865664, which states outright that
  "confirmation of FGFR4 expression is not required".

A criterion the pipeline structurally cannot produce does not belong in the
key either: `ref/genes.txt` is the accept-list the validator applies to the
model's answer, so a key requiring SET or USP9X would mark the pipeline wrong
for a symbol it is not permitted to emit. (The prompt's own gene vocabulary is
narrower still - it is the per-trial list `TrialCriteriaToGenes` finds in the
criteria text, not the whole panel.)

## Running it

    export ANTHROPIC_API_KEY=sk-ant-...          # required
    # in config.py: LLM_PLATFORM = "Anthropic", LLM_AI_MODEL = "claude-haiku-4-5-20251001"
    ./.venv/bin/python -m bench.benchmark_map

Roughly $8 and some minutes for the 50 trials on Haiku. Re-score an existing
run without spending anything:

    ./.venv/bin/python -m bench.benchmark_map --score-only

Score only the deterministic half of the diagnosis path, meaning the terms read
from the trial's own conditions plus the `_SOLID_`/`_LIQUID_` rule. It needs no
model and no network, finishes in seconds, and is identical from run to run:

    ./.venv/bin/python -m bench.benchmark_map --conditions-only

Genes and ages are not produced on that path and show as `-`. What a full
run adds on top of it is what the model contributes.

Every mode covers both registries: the 50 curated ClinicalTrials.gov keys and
the 5 CTIS keys (EU CT numbers). `--source nct|ctis|all` (default `all`)
restricts a run to one registry. Each report row carries its registry, and
the summary gives a mean for each, because 5 CTIS trials barely move the
overall mean. Conditions-only on 2026-09-24: NCT dx F1 0.74 (pop P 0.92,
R 0.78); CTIS dx F1 0.17 (pop P 0.40, R 0.27). CTIS writes conditions as
sentences ("Relapsed Acute Lymphoblastic Leukemia (ALL)"), so 3 of the 5
get no diagnosis from them. None gets a wrong one.

## What is scored

| dimension | how |
|---|---|
| diagnoses, by name | Oncotree terms, exact set comparison: `dx_p` / `dx_r` / `dx_f1` |
| diagnoses, by population | each side expanded to the Oncotree nodes a patient can be coded to, then compared: `pop_p` / `pop_r` |
| genes | `hugo_symbol` values, exact set comparison |
| age | `age_numerical` bounds, exact set comparison after normalising `<` to `<=` |
| structure | genes asserted present *and* absent in the same AND branch - the shape that matches zero patients |

## Reading the result

The means are a summary, not a verdict. Scoring by name punishes a
defensible choice at a different level of the Oncotree hierarchy exactly as
hard as a wrong answer. `Myeloid Neoplasm` against the 31 AML subtypes
beneath it scores 0.0 either way. The population columns separate those two
cases: that example is recall 1.0 with precision 0.31, meaning too broad
rather than wrong. When the two metrics disagree, trust the population
columns. Read `pop_missed` and `pop_extra` in `bench/report.json` before
concluding anything.

`UNSATISFIABLE` is different: it is unambiguous. A trial flagged there matches
no patient at all, whatever the F1 says.

## Calibration

The scorer was validated three ways:

    answer key vs itself      dx F1 1.00   gene F1 1.00   age F1 1.00   (identity)
    answers shuffled by one   dx F1 0.05   gene F1 0.26   age F1 0.15   (wrong but well-formed)
    flattened MYCN AND        flagged      (and the correct OR is not)

So 1.00 means agreement and ~0.05 means chance on diagnoses. The gene floor is
higher because 26 trials have no genomic criterion, and empty-versus-empty
scores 1.0; read the gene mean alongside the count of trials that actually
carry genes, not on its own.

The population metric calibrates to identity 1.00 and shuffled
**P 0.15 / R 0.15** (F1 0.07). Its chance floor sits above the name metric's
0.05 because two unrelated trials still share patients when either one is a
basket. Do not read 0.15 as signal.

## Why diagnoses are scored by population

Name comparison asks whether the output uses the key's words. The question
that matters is whether a patient's code reaches the trial. The two disagree
in both directions:

- *Kinder by population*: the key lists `Rhabdomyosarcoma` and its subtypes,
  the output lists the parent alone. By name that scores 0.40, but both reach
  the same patients (NCT04625907, NCT06023641).
- *Harsher by population*: the output names `Diffuse Glioma` (24 nodes)
  where the key names only one child of it, `Diffuse Midline Glioma, H3
  K27-Altered`. By name that is one extra term; by population it is every
  diffuse glioma subtype (NCT04185038: F1 0.88 by name, pop P 0.35).
- *Graded instead of zero*: the key says `_SOLID_` and the output names two
  entities. By name that is 0.0, the same as a wrong answer. By population
  it is recall 0.02, the worst miss in the set (NCT02332668).

Patients are assumed to be coded at the most specific node, as Kispi's
pipeline does. That is a leaf, or an internal node that has no ", NOS"
child: Oncotree has no `Osteosarcoma, NOS`, so an osteosarcoma that is not
subtyped further is coded `Osteosarcoma`. The only nodes a patient is never
coded to are the 20 parents that have a ", NOS" child; that patient goes to
the NOS leaf. The rule lives in `utils.build_trial_index.diagnosis_population`.

Read `pop_r` and `pop_p` apart. A recall miss is a patient who never sees a
trial they qualify for. A precision miss is a clinician rejecting a trial by
hand. Every codable node counts once, so a rare subtype weighs as much as a
common one.

Conditions-only baseline, 2026-09-23:

    by name          P 0.90   R 0.65   F1 0.72   20 trials exact
    by population    P 0.92   R 0.75   F1 0.76   23 trials exact

## Why age scores the bounds and not the label

The trial-level `age` label ("Children" / "All") was scored until 2026-09-15.
It was the wrong target twice over. MatchMiner does not match on it - it
matches on `age_numerical` in the tree - and the label is derived
deterministically from the trial's `stdAges` bands, so scoring it compared a
ClinicalTrials.gov fact against a curator's clinical judgement. 35 of 49
trials disagreed, always in the same direction, and the column measured the
curator rather than the pipeline. The key now takes whatever `map_age_group`
derives, and the column scores the bounds that actually select patients.

`<` and `<=` are normalised together because MatchMiner's query transformer
maps both to the same Mongo operator, so `<18` and `<=18` select identical
patients and must not count as different answers.

Every answer was re-curated against the trial's own age sentence. On the
structured fields alone the column scores about 0.76. Of the 16
disagreements, 11 are trials whose sponsor put an *exclusive* bound in
`maximumAge`, where the completed-units reading is a year too wide, and 5
state a bound only in prose.

Since 2026-09-23 the mapper also reads the age sentence (`utils/age_bounds.py`),
and a full run should score about 0.92. That figure was measured with the
production prompt on claude-haiku-4-5: 44 of 50 trials exact, none worse
than the structured reading. The remaining gaps are neuroblastoma risk
definitions that contain ages, and one structured minimum that disagrees with
the prose; both are listed in `doc/open_issues.md`. `--conditions-only` does
not produce ages.
