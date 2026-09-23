#!/bin/bash

# Sync trials to CTML and rebuild the flat index.
# Runs 'pull --all', 'map --all' and the index build once, then exits.
#
# SOURCE selects the registries: all (default), nct or ctis.
#     SOURCE=nct ./sync_trials.sh
SOURCE="${SOURCE:-all}"

echo "========================================"
echo "    NCT2CTML Trial Sync"
echo "========================================"
echo "Starting trial sync at $(date '+%Y-%m-%d %H:%M:%S')"
echo

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "ERROR: main.py not found"
    echo "Please run this script from the nct2ctml directory"
    exit 1
fi

# Source the conda initialization and call the function
source ~/.init_conda
init_conda

# Activate the conda environment
ENV_NAME="nct2ctml"

# Check if conda environment exists
if conda list -n "$ENV_NAME" >/dev/null 2>&1; then
    echo "Activating conda environment: $ENV_NAME"
    conda activate "$ENV_NAME"
else
    echo "Creating conda environment: $ENV_NAME"
    conda create -n "$ENV_NAME" python=3.12 -y
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create conda environment '$ENV_NAME'"
        exit 1
    fi
    
    echo "Activating newly created conda environment: $ENV_NAME"
    conda activate "$ENV_NAME"
    
    echo "Installing requirements from requirements.txt..."
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
        if [ $? -ne 0 ]; then
            echo "ERROR: Failed to install requirements"
            exit 1
        fi
        echo "Requirements installed successfully"
    else
        echo "WARNING: requirements.txt not found, skipping package installation"
    fi
fi

# Run pull all
echo "Step 1: Pulling trials (source: $SOURCE)..."
echo "Running: python main.py pull --all --source $SOURCE"
python main.py pull --all --source "$SOURCE"
PULL_EXIT_CODE=$?

if [ $PULL_EXIT_CODE -ne 0 ]; then
    echo "ERROR: Trial pull failed with exit code $PULL_EXIT_CODE"
    exit $PULL_EXIT_CODE
fi

echo "Trial pull completed successfully"
echo

# Run map all
# Uses MAPPING_CUTOFF_DAYS days from config.py.
# Maps the trials for which last_updated_date is within MAPPING_CUTOFF_DAYS days.
echo "Step 2: Mapping trials to CTML..."
echo "Running: python main.py map --all --source $SOURCE"
python main.py map --all --source "$SOURCE"
MAP_EXIT_CODE=$?

if [ $MAP_EXIT_CODE -ne 0 ]; then
    echo "ERROR: Trial mapping failed with exit code $MAP_EXIT_CODE"
    exit $MAP_EXIT_CODE
fi

echo "Trial mapping completed successfully"
echo

# Rebuild the index over mapped, needs-review and reviewed trials. Not
# --strict: trials whose protein change failed its check are in the review
# queue by design, and the index reports them in protein_check.
echo "Step 3: Rebuilding the flat index..."
echo "Running: python -m utils.build_trial_index"
python -m utils.build_trial_index
INDEX_EXIT_CODE=$?

if [ $INDEX_EXIT_CODE -ne 0 ]; then
    echo "ERROR: Index build failed with exit code $INDEX_EXIT_CODE"
    exit $INDEX_EXIT_CODE
fi
echo
echo "========================================"
echo "Trial sync completed at $(date '+%Y-%m-%d %H:%M:%S')"
