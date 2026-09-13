# Benchmarking the automated mapping

`ctml/reviewed/NCT*.yaml` are hand-curated and verified end-to-end in
MatchMiner. They are the answer key. This harness runs the pipeline over the
same trials and scores the result, so the question "can the LLM curate CTML?"
is settled with numbers rather than impressions.

## Running it

    export ANTHROPIC_API_KEY=sk-ant-...          # required
    # in config.py: LLM_PLATFORM = "Anthropic", LLM_AI_MODEL = "claude-haiku-4-5-20251001"
    ./.venv/bin/python -m bench.benchmark_map

Roughly $2 and a few minutes for the 12 trials on Haiku. Re-score an existing
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

    answer key vs itself      dx F1 1.00   (identity)
    answers shuffled by one   dx F1 0.05   (wrong but well-formed)
    flattened MYCN AND        flagged      (and the correct OR is not)

So 1.00 means agreement and ~0.05 means chance. Anything in between is a real
signal about the model.
