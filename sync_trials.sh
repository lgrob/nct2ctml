#!/bin/bash
# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

# Sync trials to CTML and rebuild the flat index.
# Runs 'pull --all', 'map --all' and the index build once, then exits.
#
# SOURCE selects the registries: all (default), nct or ctis.
#     SOURCE=nct ./sync_trials.sh
# PYTHON is the interpreter, as in scripts/run_ollama_mapping.sh; default
# ./.venv/bin/python. For a conda environment:
#     PYTHON="$(conda run -n nct2ctml which python)" ./sync_trials.sh
#
# The environment is not created here. Build it once from the lock, so an
# unattended run uses the versions the tests passed with rather than
# whatever is newest on the day:
#     python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.lock
#
# Only one sync runs at a time: a second one started while the first holds
# the lock exits with status 75 and changes nothing.
set -euo pipefail

SOURCE="${SOURCE:-all}"

# Run from the checkout whatever the caller's directory (cron starts in $HOME).
cd "$(dirname "$0")"

PY="${PYTHON:-./.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "ERROR: no interpreter at $PY. Create the environment first:"
    echo "  python3.12 -m venv .venv && ./.venv/bin/pip install -r requirements.lock"
    echo "or point PYTHON at one."
    exit 1
fi

# mkdir is atomic on every filesystem, and flock is not on macOS. The pid
# inside lets a lock left by a killed run be recognised and taken over.
LOCK="cache/sync.lock"
mkdir -p cache
if ! mkdir "$LOCK" 2>/dev/null; then
    HOLDER="$(cat "$LOCK/pid" 2>/dev/null || true)"
    if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
        echo "Another sync is running (pid $HOLDER, lock $LOCK); not starting."
        exit 75
    fi
    echo "Removing a stale lock left by pid ${HOLDER:-unknown}"
    rm -rf "$LOCK"
    mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

step() {
    echo "Running: $*"
    "$@" || { status=$?; echo "ERROR: '$*' failed with exit code $status"; exit "$status"; }
    echo
}

echo "========================================"
echo "    NCT2CTML Trial Sync"
echo "========================================"
echo "Starting trial sync at $(date '+%Y-%m-%d %H:%M:%S') with $("$PY" -V 2>&1) ($PY)"
echo

echo "Step 1: Pulling trials (source: $SOURCE)..."
step "$PY" main.py pull --all --source "$SOURCE"

# Maps the trials whose last_updated_date is within MAPPING_CUTOFF_DAYS days
# (config.py). The run's model calls are recorded under runs/.
echo "Step 2: Mapping trials to CTML..."
step "$PY" main.py map --all --source "$SOURCE"

# Rebuild the index over mapped, needs-review and reviewed trials. Not
# --strict: trials whose protein change failed its check are in the review
# queue by design, and the index reports them in protein_check.
echo "Step 3: Rebuilding the flat index..."
step "$PY" -m utils.build_trial_index

echo "========================================"
echo "Trial sync completed at $(date '+%Y-%m-%d %H:%M:%S')"
