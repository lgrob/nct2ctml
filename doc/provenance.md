# Provenance and replay

What every mapped file records about how it was made, where every model call is kept, and how to rebuild a run without a model. Moved from the README on 2026-09-28.

Every mapped file ends with a `_provenance` block (`utils/provenance.py`)
saying what produced it: run id, time, git commit and whether the tree had
local changes, LLM platform, model and settings, both prompt variants
(`GENOMIC_PROMPT`, `DIAGNOSIS_INPUT`), and the SHA-256 of every reference
file. Review keeps it; the index publishes it in `trials.tsv`, and its
manifest counts trials mapped against a reference file other than the
current one (`reference_drift`).

Each `map` and benchmark run also writes `runs/<run_id>/`:

| File | What it is |
|---|---|
| `run.json` | command, code version, model and settings, reference hashes, Python and package versions; call counts once the run ends |
| `llm_calls.jsonl` | one line per model call: trial, prompt, prompt and schema SHA-256, raw response (for Anthropic with request id, answering model and token usage), time taken, or the error |
| `schemas/<sha256>.json` | each distinct schema, exactly as sent |

A full run is about 50 MB (estimated). `runs/` is gitignored but, unlike
`cache/`, cannot be regenerated: it is the only copy of what the model
answered. Keep the run a published result was built from. `RUNS_PATH = None`
in `config.py` turns recording off.

To rebuild a run's CTML without a model, answer from its record:

```bash
NCT2CTML_LLM_PLATFORM=Replay NCT2CTML_REPLAY_FILE=runs/<run_id>/llm_calls.jsonl \
    python main.py map --nct_id NCT03643276 --out /tmp/replay
```

Each call is looked up by the hash of its prompt and schema and answered
with the recorded response. A prompt the run never sent, because the code
or its inputs have changed since, fails that trial with `ReplayMiss`. So a
replay that completes shows that the deterministic code still does what it
did, and a diff against the original isolates what changed outside the model.
