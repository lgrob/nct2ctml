"""
Map trials through TrialMapManager with a schema-driven stub model and print,
per trial, where the output went and a hash of it (its _provenance block,
which carries the time, left out).

    python scripts/map_probe.py out.json NCT03643276,2023-509392-17-00

Complements scripts/determinism_probe.py, which calls the registry mappers
directly: this one also runs what TrialMapManager adds after them, the
exclusion-only diagnoses, the gene-status and ALL-lineage rules, the
contradiction checks and the routing to ctml/needs-review. Output goes to
temporary directories; nothing under cache/ or ctml/ is written. The real
LLM platform is replaced by one that refuses to send, so a stub that stops
taking effect fails instead of calling the API.
"""

import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from loguru import logger

logger.remove()
import yaml

import config
import src.trial_data_helper as tdh
import utils.ai_helper as ai
from scripts.stub_model import fake, refuse_real_platform
from src.trial_map_manager import TrialMapManager


def main(out_path, ids):
    refuse_real_platform(ai)
    ai.send_ai_request = lambda id, prompt, json_schema=None: fake(json_schema or {})
    ai.parse_ai_response = lambda response, trial_id="": response
    tdh.print = lambda *a, **k: None  # save_to_file echoes every YAML
    config.RUNS_PATH = None
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        mapped, review = os.path.join(tmp, "mapped"), os.path.join(tmp, "review")
        os.makedirs(mapped)
        os.makedirs(review)
        config.CTML_REVIEW_PATH = review
        manager = TrialMapManager()
        for trial in ids:
            if trial.startswith("NCT"):
                ok = manager.map_single_trial(trial, config.NCT_CACHE_PATH, mapped)
            else:
                ok = manager.map_single_ctis_trial(trial, config.CTIS_CACHE_PATH, mapped)
            entry = {"ok": ok}
            for layer, directory in (("mapped", mapped), ("needs_review", review)):
                path = os.path.join(directory, f"{trial}.yaml")
                if os.path.exists(path):
                    doc = yaml.safe_load(open(path))
                    doc.pop("_provenance", None)
                    text = yaml.dump(doc, sort_keys=False)
                    entry[layer] = hashlib.sha256(text.encode()).hexdigest()
            out[trial] = entry
    # A file, not stdout: the mapping code prints to stdout as it goes.
    with open(out_path, "w") as handle:
        json.dump(out, handle, indent=0, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2].split(","))
