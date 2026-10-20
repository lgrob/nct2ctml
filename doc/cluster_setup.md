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

### If `ollama pull` is blocked

Ollama's model directory is a content-addressed blob store with manifests,
not a folder of GGUF files - copying a `.gguf` into it does nothing. Import
it instead.

On a machine with internet (your laptop), fetch the weights:

    pip install huggingface_hub
    huggingface-cli download unsloth/gemma-3-27b-it-GGUF \
      gemma-3-27b-it-Q4_K_M.gguf --local-dir ./gguf

That file is ~16 GB. Move it to the cluster by whatever route your site
sanctions for large files, then on the cluster:

    cat > Modelfile <<'EOF'
    FROM /path/on/cluster/gemma-3-27b-it-Q4_K_M.gguf
    EOF

    # server must be running; this writes into $OLLAMA_MODELS
    apptainer exec --bind "$OLLAMA_MODELS:/root/.ollama/models" \
      "$OLLAMA_SIF" ollama create gemma3-27b -f Modelfile

Then set `LLM_AI_MODEL = "gemma3-27b"` - the name you gave `ollama create`,
not the HuggingFace path.

Check the import took the chat template with it:

    apptainer exec "$OLLAMA_SIF" ollama show gemma3-27b --template

Modern GGUFs carry the template in their metadata and Ollama picks it up. If
that comes back empty the model will still answer but formatting will be
wrong in ways that look like poor model quality rather than a broken import -
add an explicit `TEMPLATE` block to the Modelfile if so.

The alternative, if any machine can reach the registry: run `ollama pull`
there and copy the whole `$OLLAMA_MODELS` tree across. Same bytes, no
Modelfile, but you must copy the manifests as well as the blobs.

## 3. Config

`config.py` stays as committed (since 2026-10-01 that is Ollama with
`gpt-oss:120b`, the adopted backend); set anything else in the job's
environment instead, so the repository never says one thing while the cluster
runs another:

    export NCT2CTML_LLM_PLATFORM=Ollama
    export NCT2CTML_LLM_AI_MODEL=llama3.3:70b      # or gemma3:27b; see doc/llm_backends.md
    export NCT2CTML_OLLAMA_NUM_CTX=32768           # 8192 was a 16 GB laptop limit
    export NCT2CTML_LLM_REQUEST_TIMEOUT_SECONDS=300  # 1200 assumed 2.4 tok/s

`GPU_SERVER_HOSTNAME` already defaults to `http://127.0.0.1`, which is right
for a server in the same job (`localhost` or `0.0.0.0` can be routed to a
proxy; `config.py` says why). `scripts/run_ollama_mapping.sh` refuses to run
unless the platform is Ollama, and exports the model it pulled. Every
override is logged at startup and recorded in the run's `run.json`.

`OLLAMA_NUM_CTX` matters: the longest criteria text in the corpus is ~4,900
tokens before the prompt wrapper, gene list and oncotree terms are added, and
Ollama truncates an over-long prompt **silently** rather than erroring.

## Credentials, for the Anthropic backend

Only this backend needs a secret, and a cluster is the awkward place to keep
one: the project directory is a group share, and the compute nodes are
shared. Three places the key must never go.

- **Anywhere under the project share**, the repository checkout included.
  Everyone on the project can read it.
- **A job script, or `--export`.** Slurm copies the batch script into its
  spool, and `--export=ANTHROPIC_API_KEY=...` writes the value into the job
  record. `scripts/run_anthropic_mapping.sh` refuses to start if it finds the
  name in `SLURM_EXPORT_ENV`.
- **Any command line.** Other users can read `ps` on a shared node, and
  `utils/provenance.py` records `argv` verbatim into `runs/<id>/run.json`,
  which is committed. Nothing else in the run record can carry the key:
  `run.json` holds the parsed `NCT2CTML_*` overrides, not the environment,
  and `ANTHROPIC_API_KEY` is not one of them.

Keep it in `$HOME` instead, readable only by you:

    mkdir -p ~/.config/nct2ctml && chmod 700 ~/.config/nct2ctml
    read -rs KEY
    ( umask 077; printf 'export ANTHROPIC_API_KEY=%s\n' "$KEY" > ~/.config/nct2ctml/anthropic.env )
    unset KEY

`read -rs` keeps it off the screen and out of shell history. Then check the
one thing that decides whether this is actually private - on many sites
`$HOME` is world-readable by default:

    ls -ld ~                 # want drwx------ ; otherwise chmod 700 ~
    getfacl ~ 2>/dev/null    # if the site uses ACLs, check group and other

The submit script sources that file, refuses it if it is not mode 600 or 400,
and never echoes it. `--export=ALL` would also carry the variable from your
login shell, but it fails open: the job starts and dies on the first call. A
container needs the `APPTAINERENV_`/`SINGULARITYENV_` prefix, which reads from
the parent environment - `--env KEY=value` would put it in `ps`.

## 4. Run

    sbatch scripts/run_ollama_mapping.sh benchmark   # 12 trials, scored
    sbatch scripts/run_ollama_mapping.sh map-all     # the whole corpus

The Anthropic backend has its own script. It needs no GPU, no image and no
weights, so it asks for 4 CPUs and 8 GB and runs on any node; what it does
need is a long wall clock and the key above:

    sbatch scripts/run_anthropic_mapping.sh smoke       # roadmap 0.4: 3 trials
    sbatch scripts/run_anthropic_mapping.sh benchmark
    sbatch --time=24:00:00 scripts/run_anthropic_mapping.sh map-all

It sets `NCT2CTML_LLM_PLATFORM=Anthropic` itself, refuses a non-Claude model
id, and makes one ~50-token call through `utils/llm/transport` before any
mapping - the counterpart of the Ollama script's "is it on the GPU?" check,
because auth, model access and the forced-tool shape all fail on call 1 and
would otherwise fail after the queue wait. At the end it reports calls, API
errors and tokens per trial from the run record, which is what roadmap 0.4
asks to be logged.

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
