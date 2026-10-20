#!/bin/bash
# Run the nct2ctml mapping against the Anthropic API from a cluster job.
#
#   sbatch scripts/run_anthropic_mapping.sh smoke       # roadmap 0.4: 3 trials
#   sbatch scripts/run_anthropic_mapping.sh benchmark   # the curated trials
#   sbatch --time=24:00:00 scripts/run_anthropic_mapping.sh map-all
#   (SOURCE=nct|ctis for one registry, CUTOFF_DAYS=N for recent NCT trials)
#
# The Anthropic backend is an HTTPS client, so unlike
# scripts/run_ollama_mapping.sh this job needs no GPU, no Apptainer image and
# no model weights - only outbound network and a key. It is slow in wall time
# and idle in CPU, so ask for hours rather than cores.
#
# THE KEY IS NEVER PASSED TO THIS SCRIPT, on the command line or through
# --export. It is read from a file in $HOME; see "Credentials" in
# doc/cluster_setup.md for why and how to put it there.
#
#SBATCH --job-name=nct2ctml-anthropic
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=logs/anthropic_%j.out

set -euo pipefail
MODE="${1:-smoke}"

# --- paths ----------------------------------------------------------------
# As in the Ollama script: default to the submit directory rather than a
# guessed path, so the job log and the run records land in one tree.
REPO="${REPO:-${SLURM_SUBMIT_DIR:-$PWD}}"
PY="${PYTHON:-./.venv/bin/python}"
KEY_FILE="${ANTHROPIC_KEY_FILE:-$HOME/.config/nct2ctml/anthropic.env}"
MODEL_DEFAULT="claude-haiku-4-5-20251001"

if [ ! -f "$REPO/main.py" ]; then
  echo "FATAL: \$REPO=$REPO does not look like the nct2ctml checkout (no main.py)."
  echo "Submit from the repo, or pass: sbatch --export=ALL,REPO=/path/to/nct2ctml ..."
  exit 1
fi
mkdir -p "$REPO/logs"
cd "$REPO"
# `python -c` and `python -` normally put the working directory on sys.path,
# but not when PYTHONSAFEPATH is set - which some sites do, and then every
# `import config` below fails with ModuleNotFoundError rather than anything
# that names the cause. Be explicit instead of relying on the default.
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"

if [ ! -x "$PY" ]; then
  echo "FATAL: no interpreter at $PY. Create the venv first:"
  echo "  python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.lock"
  exit 1
fi

# --- credentials ----------------------------------------------------------
# A key given through --export is written into the job record, which any user
# who can see the job can read. Refuse rather than leak it; Slurm puts the
# --export argument in SLURM_EXPORT_ENV.
case "${SLURM_EXPORT_ENV:-}" in
  *ANTHROPIC_API_KEY=*)
    echo "FATAL: the key was passed through --export, which stores it in the job record."
    echo "Remove it from the sbatch line and put it in $KEY_FILE instead."
    exit 1 ;;
esac

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  if [ ! -f "$KEY_FILE" ]; then
    echo "FATAL: no ANTHROPIC_API_KEY in the environment and no key file at $KEY_FILE."
    echo "Create it once, outside the group share, readable only by you:"
    echo "  mkdir -p ~/.config/nct2ctml && chmod 700 ~/.config/nct2ctml"
    echo "  read -rs KEY"
    echo "  ( umask 077; printf 'export ANTHROPIC_API_KEY=%s\\n' \"\$KEY\" > $KEY_FILE )"
    echo "  unset KEY"
    exit 1
  fi
  # The project directory is a group share; $HOME usually is not, but on many
  # sites it is world-readable by default. Check the file this job is about to
  # read rather than assume.
  PERM="$(stat -c '%a' "$KEY_FILE" 2>/dev/null || stat -f '%Lp' "$KEY_FILE")"
  case "$PERM" in
    600|400) ;;
    *) echo "FATAL: $KEY_FILE is mode $PERM; anyone in your group or on the node can read it."
       echo "       chmod 600 $KEY_FILE   (and check: ls -ld ~)"
       exit 1 ;;
  esac
  # shellcheck disable=SC1090
  source "$KEY_FILE"
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "FATAL: $KEY_FILE did not set ANTHROPIC_API_KEY."
  exit 1
fi
# Never echoed, not even partially: the job log is written into the repo tree.
# A literal "~" in the replacement of ${var/pattern/repl} is tilde-expanded
# back to $HOME, so it has to come from a variable.
TILDE='~'
echo "[$(date +%T)] ANTHROPIC_API_KEY present (from ${KEY_FILE/#$HOME/$TILDE})"

# --- backend ---------------------------------------------------------------
# config.py defaults to Ollama with gpt-oss:120b (the adopted backend), so a
# Claude run has to say so. Set it here rather than ask the caller, and refuse
# a non-Claude model id, which would otherwise reach the Anthropic API as a
# 404 well into the run.
export NCT2CTML_LLM_PLATFORM=Anthropic
export NCT2CTML_LLM_AI_MODEL="${NCT2CTML_LLM_AI_MODEL:-$MODEL_DEFAULT}"
MODEL="$($PY -c 'import config; print(config.LLM_AI_MODEL)')"
case "$MODEL" in
  claude-*) ;;
  *) echo "FATAL: NCT2CTML_LLM_AI_MODEL=$MODEL is not a Claude model id."; exit 1 ;;
esac
# Haiku 4.5 rejects both; AnthropicPlatform raises on them, but a job that
# dies after the scheduler queue is a wasted turnaround.
case "$MODEL" in
  claude-haiku-4-5*)
    if [ -n "${NCT2CTML_ANTHROPIC_THINKING:-}" ] || [ -n "${NCT2CTML_ANTHROPIC_EFFORT:-}" ]; then
      echo "FATAL: $MODEL rejects thinking and effort. Unset NCT2CTML_ANTHROPIC_THINKING/EFFORT."
      exit 1
    fi ;;
esac
echo "[$(date +%T)] repo=$REPO  model=$MODEL  anthropic=$($PY -c 'import anthropic; print(anthropic.__version__)')"

# --- preflight: one real call ---------------------------------------------
# The counterpart of the Ollama script's "is it actually on the GPU?" check.
# Auth, model access and the forced-tool request shape all fail on call 1, and
# without this they fail after the job has been queued and started mapping.
# ~50 tokens, through utils/llm/transport so it exercises the production path.
echo "[$(date +%T)] preflight: one live call through utils.llm.transport"
$PY - <<'PREFLIGHT' || { echo "FAILED: the preflight call did not succeed (see above)."; exit 1; }
import sys
import utils.llm.transport as transport

schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
raw = transport.send_ai_request("preflight", "Set ok to true.", schema)
answer = transport.parse_ai_response(raw, "preflight")
usage = (raw or {}).get("usage") or {}
print(f"  served model: {(raw or {}).get('model')}")
print(f"  usage: in={usage.get('input_tokens')} out={usage.get('output_tokens')}")
if not isinstance(answer, dict) or "ok" not in answer:
    print(f"  the call returned no usable answer: {answer!r}")
    sys.exit(1)
print("  forced-tool JSON came back intact")
PREFLIGHT

# --- run -------------------------------------------------------------------
# Remember which run records exist now, so the summary covers exactly the
# ones this job creates: map-all starts two (NCT, then CTIS), and a run
# directory is named by its start time, not by this job.
mkdir -p runs
ls -1 runs > "logs/.runs_before_${SLURM_JOB_ID:-$$}"
case "$MODE" in
  smoke)
    # Roadmap 0.4: three benchmark trials through the production map path.
    # Acceptance is "3 trials mapped, no API errors, cost per trial logged".
    #
    # Through the benchmark rather than three `main.py map --nct_id` calls,
    # for three reasons: one run record instead of one per trial (each `map`
    # starts its own); a trial routed to review stays inside $OUT instead of
    # landing in the curators' ctml/needs-review (bench.benchmark_map
    # .review_dir); and the three trials are scored against the answer key,
    # so a run that makes calls but maps badly is visible too. The output goes
    # under the repo, not /tmp, which on a compute node is node-local and
    # usually wiped when the job ends.
    OUT="${OUT:-bench/output-anthropic-smoke-${SLURM_JOB_ID:-local}}"
    echo "[$(date +%T)] smoke: the first 3 curated NCT trials -> $OUT"
    $PY -m bench.benchmark_map --source nct --limit "${SMOKE_N:-3}" \
        --out "$OUT" --json "$OUT/report.json"
    ;;
  benchmark)
    TAG="$(echo "$MODEL" | tr ':/' '--')${REP:+-rep$REP}"
    OUT="bench/output-$TAG"
    echo "[$(date +%T)] benchmarking against the curated trials -> $OUT"
    $PY -m bench.benchmark_map --out "$OUT" --json "$OUT/report.json"
    ;;
  map-all)
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
    echo "unknown mode '$MODE' (expected: smoke | benchmark | map-all)"; exit 2 ;;
esac

# --- what it cost ----------------------------------------------------------
# AnthropicPlatform.send returns the per-call usage and provenance.record_call
# stores the whole response, so the run record carries the token counts. Price
# is deliberately not applied here: the rate card changes and a stale constant
# in a script is worse than none.
BEFORE_FILE="logs/.runs_before_${SLURM_JOB_ID:-$$}"
NEW_RUNS="$(ls -1 runs | grep -vxF -f "$BEFORE_FILE" || true)"
rm -f "$BEFORE_FILE"
if [ -z "$NEW_RUNS" ]; then
  echo "WARNING: this job created no run record under runs/, so nothing was mapped."
else
  echo "[$(date +%T)] run records from this job:"
  for R in $NEW_RUNS; do echo "  runs/$R"; done
  # shellcheck disable=SC2086
  $PY - $NEW_RUNS <<'SUMMARY'
import collections, json, sys

calls = errors = tok_in = tok_out = 0
per_trial = collections.Counter()
error_kinds = collections.Counter()
for run_id in sys.argv[1:]:
    with open(f"runs/{run_id}/llm_calls.jsonl", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            call = json.loads(line)
            calls += 1
            if call.get("error") is not None:
                errors += 1
                error_kinds[str(call["error"]).split(":")[0][:60]] += 1
                continue
            usage = ((call.get("response") or {}).get("usage")) or {}
            tok_in += usage.get("input_tokens") or 0
            tok_out += usage.get("output_tokens") or 0
            per_trial[call.get("trial_id")] += 1
n = len(per_trial) or 1
print(f"  calls {calls}, API errors {errors}, trials with calls {len(per_trial)}")
for kind, count in error_kinds.most_common(5):
    print(f"    {count} x {kind}")
print(f"  tokens in {tok_in:,} out {tok_out:,}")
print(f"  per trial: {calls / n:.1f} calls, {tok_in / n:,.0f} in, {tok_out / n:,.0f} out")
print("  multiply by the current rate card for the cost per trial")
SUMMARY
fi
echo "[$(date +%T)] done"
