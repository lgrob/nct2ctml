# Running the mapping on a GPU cluster

Ollama on a cluster, in order. Written for Apptainer + Slurm; adapt the
scheduler bits to your site.

## 1. Model weights

~16 GB for a 27B at Q4. Put them on scratch or project space, never in the
container (read-only) and preferably not `$HOME` (usually quota'd small):

    export OLLAMA_MODELS=$SCRATCH/ollama-models

If the cluster allows outbound network, the job script pulls the model on
first run. If it does not, `ollama pull` fails and the weights must be staged
in through the site's data-transfer process. Test egress early - it also
decides whether `main.py pull` can refresh trial data in place.

## 2. Trial cache

`cache/` is gitignored, so a fresh clone has no trial data. Either:

    python main.py pull --all                  # needs egress
    python main.py pull --all --source ctis

or transfer it - `tar czf cache.tgz cache/` is ~10-15 MB compressed for the
1,257 cached records.

Nothing else is missing from a clone. `ref/Census_gene_list.csv` and
`ref/.ncbi_gene_cache.json` are untracked but neither is read at runtime.

## 3. Config

    LLM_PLATFORM = "Ollama"
    LLM_AI_MODEL = "hf.co/unsloth/gemma-3-27b-it-GGUF:Q4_K_M"
    GPU_SERVER_HOSTNAME = "http://localhost"    # server runs in the same job
    OLLAMA_NUM_CTX = 32768                      # 8192 was a 16 GB laptop limit
    LLM_REQUEST_TIMEOUT_SECONDS = 300           # 1200 assumed 2.4 tok/s

`OLLAMA_NUM_CTX` matters: the longest criteria text in the corpus is ~4,900
tokens before the prompt wrapper, gene list and oncotree terms are added, and
Ollama truncates an over-long prompt **silently** rather than erroring.

## 4. Run

    sbatch scripts/run_ollama_mapping.sh benchmark   # 12 trials, scored
    sbatch scripts/run_ollama_mapping.sh map-all     # the whole corpus

Benchmark first. It scores the model against hand-curated CTML, so "is this
model good enough" is answered before spending hours on the corpus.

## The failure to watch for

Ollama starts happily without GPU access and runs on CPU at roughly 1/20th
the speed, with no error. The job script calls `ollama ps` and reports the
placement; if it says CPU, stop and fix `--nv` or the driver rather than
letting a 30-hour run become a 25-day one.

Reference points measured on a 16 GB M3 laptop with no GPU, using a 14B
model: 2.4 tokens/sec, ~28 minutes per trial, ~12 days for the corpus. A 27B
at Q4 on a datacentre GPU should be 1-2 minutes per trial.

## Reading the benchmark

The scorer is calibrated: the answer key against itself scores 1.00,
deliberately wrong answers score 0.05. Above ~0.7 with no `UNSATISFIABLE`
flags is usable behind human review; below ~0.4 no amount of prompt work
will rescue it. Run it twice - these models are non-deterministic, and the
spread between two runs of the same model tells you whether a gap between
two models is real.
