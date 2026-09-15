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

## What is scored

| dimension | how |
|---|---|
| diagnoses | Oncotree terms, exact set comparison: precision / recall / F1 |
| genes | `hugo_symbol` values, exact set comparison |
| age | the trial-level `age` label |
| structure | genes asserted present *and* absent in the same AND branch - the shape that matches zero patients |

## Reading the result

The means are a summary, not a verdict. Diagnosis scoring is exact-set, which
punishes a defensible choice at a different level of the Oncotree hierarchy
exactly as hard as a wrong answer - `Myeloid Neoplasm` versus the 20 AML
subtypes beneath it scores 0.0 either way. Read `dx_missed` and `dx_spurious`
in `bench/report.json` before concluding anything.

`UNSATISFIABLE` is different: it is unambiguous. A trial flagged there matches
no patient at all, whatever the F1 says.

## Calibration

The scorer was validated three ways:

    answer key vs itself      dx F1 1.00   gene F1 1.00   (identity)
    answers shuffled by one   dx F1 0.05   gene F1 0.26   (wrong but well-formed)
    flattened MYCN AND        flagged      (and the correct OR is not)

So 1.00 means agreement and ~0.05 means chance on diagnoses. The gene floor is
higher because 26 trials have no genomic criterion, and empty-versus-empty
scores 1.0; read the gene mean alongside the count of trials that actually
carry genes, not on its own.
