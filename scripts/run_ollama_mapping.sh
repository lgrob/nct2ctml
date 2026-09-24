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
#SBATCH --job-name=nct2ctml
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
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
  echo "  python -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi
# config.py selects the Anthropic API as the production backend. This script
# is for the GPU backend only: refuse to run rather than ask Ollama to pull a
# Claude model id, or map with the wrong backend.
PLATFORM="$($PY -c 'import config; print(config.LLM_PLATFORM)')"
if [ "$PLATFORM" != "Ollama" ]; then
    echo "ERROR: config.LLM_PLATFORM is '$PLATFORM'. Set LLM_PLATFORM = \"Ollama\" and an"
    echo "       Ollama LLM_AI_MODEL in config.py to use this script."
    exit 1
fi
MODEL="${MODEL:-$($PY -c 'import config; print(config.LLM_AI_MODEL)')}"
NUM_CTX=$($PY -c 'import config; print(getattr(config,"OLLAMA_NUM_CTX",0))')

echo "[$(date +%T)] repo=$REPO"
echo "[$(date +%T)] models=$OLLAMA_MODELS"
echo "[$(date +%T)] sif=$SIF"
echo "[$(date +%T)] model=$MODEL  num_ctx=$NUM_CTX  (both from config.py)"

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

# --- 1. start the server ---------------------------------------------------
# --nv exposes the NVIDIA stack. Without it Ollama starts happily and runs on
# CPU at roughly 1/20th the speed, with no error - the failure this script
# exists to catch.
echo "[$(date +%T)] starting ollama from $SIF"
apptainer exec --nv \
  --bind "$OLLAMA_MODELS:$OLLAMA_MODELS" \
  "$SIF" ollama serve > logs/ollama_server.log 2>&1 &
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
  apptainer exec --nv --bind "$OLLAMA_MODELS:$OLLAMA_MODELS" \
    "$SIF" ollama pull "$MODEL" || {
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
    # 50, not 12: the key was expanded on 2026-09-14. bench/benchmark_map.py
    # filters to NCT* ids, so the five curated CTIS trials are NOT scored -
    # a quarter of the corpus is unmeasured by this run.
    echo "[$(date +%T)] benchmarking against the 50 curated NCT trials"
    $PY -m bench.benchmark_map
    ;;
  map-all)
    echo "[$(date +%T)] mapping the full NCT corpus"
    $PY main.py map --all
    echo "[$(date +%T)] mapping the CTIS corpus"
    $PY main.py map --all --source ctis
    ;;
  *)
    echo "unknown mode '$MODE' (expected: benchmark | map-all)"; exit 2 ;;
esac
echo "[$(date +%T)] done"
