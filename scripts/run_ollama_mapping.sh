#!/bin/bash
# Run Ollama and the nct2ctml mapping in one cluster job.
#
# Server and client live in the same job on the same node, so nothing has to
# be discoverable across nodes and the server dies with the job rather than
# leaking. Adapt the scheduler directives to your site.
#
#   sbatch scripts/run_ollama_mapping.sh benchmark
#   sbatch scripts/run_ollama_mapping.sh map-all
#
# The defaults are the adopted backend, gpt-oss:120b with think=low
# (doc/decisions/2026-10-01-gpt-oss-backend.md). It needs an 80 GB GPU
# (~65 GB of weights, hence --mem=96G below), and the full corpus takes about
# a minute a trial, so map-all needs a longer limit than the default:
#
#   sbatch --export=ALL,OLLAMA_SIF=...,OLLAMA_MODELS=... \
#     scripts/run_ollama_mapping.sh benchmark
#   sbatch --time=24:00:00 --export=ALL,OLLAMA_SIF=...,OLLAMA_MODELS=... \
#     scripts/run_ollama_mapping.sh map-all       # every cached trial
#   (SOURCE=nct|ctis for one registry, CUTOFF_DAYS=N for recent NCT trials only)
#
# Another model through NCT2CTML_* variables (doc/llm_backends.md), e.g.
#   --export=ALL,...,NCT2CTML_LLM_AI_MODEL=qwen3.6:27b,NCT2CTML_OLLAMA_THINK=false
#
# REP=2 (etc.) keeps a replicate's output apart from the first one's.
#
#SBATCH --job-name=nct2ctml
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --output=logs/ollama_%j.out

set -euo pipefail
MODE="${1:-benchmark}"

# --- paths you must set for your site -------------------------------------
SIF="${OLLAMA_SIF:-$HOME/containers/ollama.sif}"
# Default to wherever sbatch was run from, not a guessed path: Slurm writes
# --output relative to the submit directory, so anything else splits the job
# log and the server log across two trees.
REPO="${REPO:-${SLURM_SUBMIT_DIR:-$PWD}}"
# Model weights are large (~16 GB for a 27B at Q4). Keep them off $HOME,
# which is usually quota'd small, and out of the container, which is read-only.
# Not every site sets $SCRATCH; without it, and without OLLAMA_MODELS, stop
# rather than invent a directory and pull tens of GB into it.
if [ -z "${OLLAMA_MODELS:-}" ] && [ -z "${SCRATCH:-}" ]; then
  echo "FATAL: neither OLLAMA_MODELS nor SCRATCH is set, so there is no model directory."
  echo "Point it at the directory holding your pulled models, e.g.:"
  echo "  sbatch --export=ALL,OLLAMA_MODELS=/path/to/ollama/models,... scripts/run_ollama_mapping.sh benchmark"
  exit 1
fi
export OLLAMA_MODELS="${OLLAMA_MODELS:-$SCRATCH/ollama-models}"
# Deliberately NOT a literal. The pipeline requests whatever config.py names,
# so a separate default here can drift out of step with it - pulling one model
# and then asking the server for another, which surfaces as a 404 well into
# the run.
PY="${PYTHON:-./.venv/bin/python}"

# Verify before creating. mkdir -p on a wrong REPO happily invents the
# directory, the job then runs from an empty tree, and the only symptom is a
# server log that is not where you looked for it.
if [ ! -f "$REPO/main.py" ]; then
  echo "FATAL: \$REPO=$REPO does not look like the nct2ctml checkout (no main.py)."
  echo "Submit from the repo, or pass: sbatch --export=ALL,REPO=/path/to/nct2ctml ..."
  exit 1
fi
# Talk to the local server over 127.0.0.1, not 0.0.0.0. Sites that set a
# proxy typically list localhost and 127.0.0.1 in NO_PROXY but not 0.0.0.0,
# so an ollama client defaulting to 0.0.0.0 sends its API calls to the
# corporate proxy, which cannot reach a port on this node. The server still
# only needs loopback: the client runs in the same job on the same host.
export OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}0.0.0.0"
export no_proxy="$NO_PROXY"

mkdir -p "$OLLAMA_MODELS" "$REPO/logs"
cd "$REPO"

if [ ! -x "$PY" ]; then
  echo "FATAL: no interpreter at $PY. Create the venv first:"
  echo "  python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.lock"
  exit 1
fi
# config.py defaults to Ollama with gpt-oss:120b. An override to another
# platform (NCT2CTML_LLM_PLATFORM=Anthropic) is refused here rather than
# asking Ollama to pull a Claude model id, or mapping with the wrong backend.
PLATFORM="$($PY -c 'import config; print(config.LLM_PLATFORM)')"
if [ "$PLATFORM" != "Ollama" ]; then
    echo "ERROR: config.LLM_PLATFORM is '$PLATFORM'. Run with"
    echo "       NCT2CTML_LLM_PLATFORM=Ollama NCT2CTML_LLM_AI_MODEL=<an Ollama model>, e.g. llama3.3:70b."
    exit 1
fi
MODEL="${MODEL:-$($PY -c 'import config; print(config.LLM_AI_MODEL)')}"
# The mapping reads its model from config; make it the one pulled and warmed
# up here, so MODEL=... cannot map with a different model than it loaded.
export NCT2CTML_LLM_AI_MODEL="$MODEL"
NUM_CTX=$($PY -c 'import config; print(getattr(config,"OLLAMA_NUM_CTX",0))')
THINK=$($PY -c 'import config; print(config.OLLAMA_THINK)')
NUM_PREDICT=$($PY -c 'import config; print(config.OLLAMA_NUM_PREDICT)')

echo "[$(date +%T)] repo=$REPO"
echo "[$(date +%T)] models=$OLLAMA_MODELS"
echo "[$(date +%T)] sif=$SIF"
echo "[$(date +%T)] model=$MODEL  num_ctx=$NUM_CTX  num_predict=$NUM_PREDICT  think=$THINK  (from config.py or NCT2CTML_*)"

# gpt-oss ignores think=false and reasons anyway; its reasoning then eats
# num_predict and the JSON is cut off, which scores as empty answers.
case "$MODEL" in
  gpt-oss*)
    if [ "$THINK" = "False" ]; then
      echo "ERROR: $MODEL cannot turn reasoning off. Set NCT2CTML_OLLAMA_THINK=low|medium|high"
      echo "       (and NCT2CTML_OLLAMA_NUM_PREDICT=16384)."
      exit 1
    fi ;;
esac

# A prompt longer than num_ctx is truncated silently, so a too-small window
# shows up as poor scores rather than as an error.
if [ "$NUM_CTX" -lt 16384 ]; then
  echo "WARNING: OLLAMA_NUM_CTX=$NUM_CTX. The longest trial needs ~5k tokens of"
  echo "         criteria before the prompt wrapper; 32768 is the GPU setting."
fi

# Fail here with something readable rather than letting Apptainer report a
# missing path as an encryption check failure.
if [ ! -f "$SIF" ]; then
  echo "FATAL: no Apptainer image at $SIF"
  echo "Set OLLAMA_SIF to wherever yours is, e.g.:"
  echo "  sbatch --export=ALL,OLLAMA_SIF=/path/to/ollama.sif scripts/run_ollama_mapping.sh $MODE"
  echo "Candidates found under \$HOME and \$SCRATCH:"
  find "$HOME" "${SCRATCH:-/dev/null}" -maxdepth 4 -name '*.sif' 2>/dev/null | head -10 | sed 's/^/  /'
  exit 1
fi

# Apptainer or its predecessor Singularity, whichever the site has; same flags.
CONTAINER="$(command -v apptainer || command -v singularity || true)"
if [ -z "$CONTAINER" ]; then
  echo "FATAL: neither apptainer nor singularity is on PATH (module load?)."
  exit 1
fi
# The ollama image sets OLLAMA_HOST=0.0.0.0:11434 itself, and the image's
# value wins over the one exported above. A client aimed at 0.0.0.0 goes to
# the proxy (0.0.0.0 is not in NO_PROXY) and fails with "something went
# wrong"; --env makes the container use 127.0.0.1.
CEXEC=("$CONTAINER" exec --nv --env "OLLAMA_HOST=${OLLAMA_HOST#http://}" --bind "$OLLAMA_MODELS:$OLLAMA_MODELS")

# --- 1. start the server ---------------------------------------------------
# --nv exposes the NVIDIA stack. Without it Ollama starts happily and runs on
# CPU at roughly 1/20th the speed, with no error - the failure this script
# exists to catch.
echo "[$(date +%T)] starting ollama from $SIF with $CONTAINER"
"${CEXEC[@]}" "$SIF" ollama serve > logs/ollama_server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 60); do
  curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break
  sleep 2
done
curl -sf -m 5 http://localhost:11434/api/tags >/dev/null || {
  echo "FAILED: ollama did not come up"; tail -20 logs/ollama_server.log; exit 1; }
echo "[$(date +%T)] ollama responding"

# --- 2. make sure the model is present -------------------------------------
# Ollama does not auto-pull; a missing model returns 404 at request time,
# which surfaces much later as an opaque mapping failure.
if ! curl -s http://localhost:11434/api/tags | grep -q "${MODEL%%:*}"; then
  echo "[$(date +%T)] pulling $MODEL (needs outbound network)"
  "${CEXEC[@]}" "$SIF" ollama pull "$MODEL" || {
      echo "FAILED: could not pull $MODEL."
      echo "If this cluster blocks egress, stage the GGUF into $OLLAMA_MODELS instead."
      exit 1; }
fi

# --- 3. confirm it is actually on the GPU ----------------------------------
# The whole point of the cluster. 'ollama ps' reports the split; anything
# showing CPU means --nv or the driver is not working, and the run would take
# days instead of hours.
# Load the model, then ask the API rather than parsing CLI output - 'ollama ps'
# prints nothing if the model has not finished loading, which reads as "cannot
# determine placement" when everything is in fact fine.
curl -s -m 600 http://127.0.0.1:11434/api/generate \
  -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false}" >/dev/null 2>&1 || true
PS_JSON=$(curl -s -m 15 http://127.0.0.1:11434/api/ps 2>/dev/null)
echo "[$(date +%T)] loaded: $(echo "$PS_JSON" | tr ',' '\n' | grep -iE 'size_vram|"name"' | tr '\n' ' ')"
case "$PS_JSON" in
  *size_vram*0,*|*'"size_vram":0'*) echo "  -> WARNING: size_vram is 0, the model is on CPU. Check --nv." ;;
  *size_vram*)                      echo "  -> model resident in VRAM" ;;
  *)                                echo "  -> could not read /api/ps; check nvidia-smi below" ;;
esac
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || true

# --- 4. run the work -------------------------------------------------------
case "$MODE" in
  benchmark)
    # Every curated trial, both registries (bench/README.md). One directory
    # per model and replicate, report included, so runs of different models
    # neither overwrite each other nor the tracked bench/report.json.
    TAG="$(echo "$MODEL" | tr ':/' '--')${REP:+-rep$REP}"
    OUT="bench/output-$TAG"
    echo "[$(date +%T)] benchmarking against the curated trials -> $OUT"
    $PY -m bench.benchmark_map --out "$OUT" --json "$OUT/report.json"
    ;;
  map-all)
    # Every cached trial. `map --all` alone maps only the NCT trials updated
    # in the last MAPPING_CUTOFF_DAYS (1: the nightly incremental run), so a
    # remap needs the cutoff opened; CUTOFF_DAYS=14 etc. maps recent ones
    # only. SOURCE=nct or SOURCE=ctis maps one registry. CTIS has no cutoff.
    CUTOFF_DAYS="${CUTOFF_DAYS:-36500}"
    SOURCE="${SOURCE:-all}"
    if [ "$SOURCE" != "ctis" ]; then
      echo "[$(date +%T)] mapping the NCT corpus (trials updated in the last $CUTOFF_DAYS days)"
      $PY main.py map --all --cutoff-days "$CUTOFF_DAYS"
    fi
    if [ "$SOURCE" != "nct" ]; then
      echo "[$(date +%T)] mapping the CTIS corpus"
      $PY main.py map --all --source ctis
    fi
    ;;
  *)
    echo "unknown mode '$MODE' (expected: benchmark | map-all)"; exit 2 ;;
esac
echo "[$(date +%T)] done"
