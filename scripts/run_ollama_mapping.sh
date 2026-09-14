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
MODEL="${MODEL:-gemma3:27b}"

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
echo "[$(date +%T)] repo=$REPO  models=$OLLAMA_MODELS  sif=$SIF"

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
apptainer exec --nv "$SIF" ollama run "$MODEL" "reply with OK" >/dev/null 2>&1 || true
PROCESSOR=$(apptainer exec --nv "$SIF" ollama ps 2>/dev/null | tail -n +2 | head -1)
echo "[$(date +%T)] ollama ps: $PROCESSOR"
case "$PROCESSOR" in
  *GPU*) echo "  -> running on GPU" ;;
  *CPU*) echo "  -> WARNING: running on CPU. Check --nv and the driver before continuing." ;;
  *)     echo "  -> could not determine placement; check manually with 'ollama ps'" ;;
esac
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || true

# --- 4. run the work -------------------------------------------------------
PY="${PYTHON:-./.venv/bin/python}"
case "$MODE" in
  benchmark)
    echo "[$(date +%T)] benchmarking against the 12 curated trials"
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
