# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

"""
Convert reviewed CTML from YAML to the JSON that matchminer-admin ingests.

This is the promotion step of the review gate: a file only reaches
ctml/json once a person has moved it into ctml/reviewed. matchminer-admin
POSTs whatever it finds in ctml/json to the MatchMiner API and deletes it
afterwards, so nothing should be written here that has not been reviewed.

Usage (formerly bulk_convert_yaml_to_json.py at the repo root):
    python main.py promote                    # all reviewed files
    python main.py promote NCT01 NCT02        # only these
    python main.py promote --dry-run          # list, write nothing

Nothing runs this automatically: promotion is a deliberate step after review.
"""

import json
import os
import sys

import yaml

YAML_DIR = "ctml/reviewed"
JSON_DIR = "ctml/json"


def convert(nct_ids: list[str], dry_run: bool = False) -> int:
    """Write ctml/json/<id>.json for each reviewed trial; returns how many (would be) written."""
    if not dry_run:
        os.makedirs(JSON_DIR, exist_ok=True)
    if nct_ids:
        names = [f"{n}.yaml" for n in nct_ids]
    else:
        names = sorted(f for f in os.listdir(YAML_DIR) if f.endswith((".yaml", ".yml")))
    if not names:
        print(f"No reviewed CTML in {YAML_DIR}/ - nothing to promote.")
        return 0

    written = 0
    for name in names:
        src = os.path.join(YAML_DIR, name)
        if not os.path.exists(src):
            print(f"  missing  {src}", file=sys.stderr)
            continue
        dst = os.path.join(JSON_DIR, os.path.splitext(name)[0] + ".json")
        try:
            with open(src, encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except yaml.YAMLError as e:
            # A malformed file must not be promoted: matchminer-admin would
            # either reject it or, worse, insert a partial trial.
            print(f"  INVALID  {src}: {e}", file=sys.stderr)
            continue
        if not isinstance(doc, dict) or not doc.get("nct_id"):
            print(f"  INVALID  {src}: no nct_id at the top level", file=sys.stderr)
            continue
        # MatchMiner's trial resource rejects unknown fields (allow_unknown is
        # False), and a leading underscore is Eve's own namespace. The
        # reviewed YAML keeps the block; the queue for MatchMiner does not.
        doc.pop("_provenance", None)
        if dry_run:
            print(f"  would write  {dst}")
        else:
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=4)
            print(f"  {src} -> {dst}")
        written += 1
    return written
