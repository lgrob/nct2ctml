"""
Everything a refactor must not change, in one JSON, so a move can be checked
before it is committed.

    python scripts/behaviour_snapshot.py --out before.json
    ... move code ...
    python scripts/behaviour_snapshot.py --compare before.json

It captures, from the local data (cache/, ctml/):

- prompts: every prompt, schema and CTML output of the curated trials under
  a stub model (scripts/determinism_probe.py, PYTHONHASHSEED=0);
- mapping: every mapped or queued trial through TrialMapManager under the
  same stub, which adds the exclusion, gene-status and ALL-lineage rules and
  the review routing (scripts/map_probe.py): where each output went and its
  hash. The whole corpus, because the curated trials alone trigger too few
  of those rules;
- index: the SHA-256 of each table built from the current layers;
- review: the output of `review_helper queue`, of every batch command's dry
  run, and of `check` on the first trials in the queue;
- sheets: the HTML review sheets for the queue, with the generation time
  removed.

Every step runs as a subprocess of the commands users type, so the snapshot
does not depend on how the code is laid out. The review commands run from a
scratch directory whose cache/, ctml/ and ref/ link to the real ones, so
sheets are written there. The script fails if anything under the real
cache/ctml, ctml/ or ref/ changed while it ran: every command it uses reads only.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PY = sys.executable
BATCH = [
    "flag-exclusions",
    "clear-stale-gene-flags",
    "fix-all-lineage",
    "resolve-remap-drops",
    "fix-genomic-notation",
    "flag-gene-status",
    "flag-unsupported-genes",
]
CHECKED = 15
WATCHED = ("cache/ctml", "ctml", "ref")


def run(*cmd, cwd=ROOT, env=None):
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})}
    )
    if result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
    return result.stdout


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def state():
    """(path, size, mtime) of every file the snapshot must not change."""
    out = {}
    for top in WATCHED:
        for d, _, files in os.walk(os.path.join(ROOT, top)):
            for f in files:
                p = os.path.join(d, f)
                st = os.stat(p)
                out[os.path.relpath(p, ROOT)] = (st.st_size, st.st_mtime_ns)
    return out


def curated_ids():
    return sorted(
        f[:-5]
        for f in os.listdir(os.path.join(ROOT, "ctml", "reviewed"))
        if f.endswith(".yaml")
        and any(
            os.path.exists(os.path.join(ROOT, "cache", r, f[:-5] + ".json"))
            for r in ("nct", "ctis")
        )
    )


def corpus_ids():
    """Every mapped or queued trial with a cached record: what the mapping probe re-maps."""
    ids = set()
    for d in ("cache/ctml", "ctml/needs-review"):
        path = os.path.join(ROOT, d)
        if os.path.isdir(path):
            ids |= {f[:-5] for f in os.listdir(path) if f.endswith(".yaml")}
    return sorted(
        t
        for t in ids
        if os.path.exists(
            os.path.join(ROOT, "cache", "nct" if t.startswith("NCT") else "ctis", t + ".json")
        )
    )


def prompts(ids):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "probe.json")
        run(PY, "scripts/determinism_probe.py", out, ",".join(ids), env={"PYTHONHASHSEED": "0"})
        with open(out) as handle:
            return json.load(handle)


def mapping(ids):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "map.json")
        run(PY, "scripts/map_probe.py", out, ",".join(ids), env={"PYTHONHASHSEED": "0"})
        with open(out) as handle:
            return json.load(handle)


def index():
    with tempfile.TemporaryDirectory() as tmp:
        run(PY, "-m", "utils.build_trial_index", "--out", tmp)
        return {
            name: sha(open(os.path.join(tmp, name), "rb").read())
            for name in sorted(os.listdir(tmp))
            if name.endswith(".tsv")
        }


def review():
    with tempfile.TemporaryDirectory() as tmp:
        for top in ("cache", "ctml", "ref"):
            os.symlink(os.path.join(ROOT, top), os.path.join(tmp, top))
        env = {"PYTHONPATH": ROOT}

        def cli(*args):
            return run(PY, "-m", "utils.review_helper", *args, cwd=tmp, env=env)

        out = {"queue": cli("queue")}
        for cmd in BATCH:
            out[cmd] = cli(cmd)
        # Only trial lines: creating the LLM platform prints to stdout too.
        trials = [
            line.split("\t")[0]
            for line in out["queue"].splitlines()
            if re.match(r"^(NCT\d{8}|\d{4}-\d{6}-\d{2}-\d{2})\t", line)
        ]
        for trial in trials[:CHECKED]:
            out[f"check {trial}"] = cli("check", trial)
        cli("sheets")
        sheets = {}
        sheet_dir = os.path.join(tmp, "review_sheets")
        for name in sorted(os.listdir(sheet_dir)):
            path = os.path.join(sheet_dir, name)
            if os.path.isfile(path):
                text = open(path, encoding="utf-8").read()
                sheets[name] = sha(
                    re.sub(r"generated \d{4}-\d\d-\d\d \d\d:\d\d", "generated", text)
                )
        return out, sheets


def snapshot():
    before = state()
    ids = curated_ids()
    snap = {"prompts": prompts(ids), "mapping": mapping(corpus_ids()), "index": index()}
    snap["review"], snap["sheets"] = review()
    changed = sorted(p for p, v in state().items() if before.get(p) != v)
    changed += sorted(set(before) - set(state()))
    if changed:
        sys.exit(f"the snapshot changed files it must only read: {changed[:10]}")
    return snap


def differences(now, then):
    out = []
    for section in ("prompts", "mapping", "index", "review", "sheets"):
        a, b = then.get(section, {}), now.get(section, {})
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                out.append(f"{section}: {key}")
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", help="write the snapshot here")
    group.add_argument("--compare", help="compare with a snapshot written earlier")
    args = ap.parse_args()

    snap = snapshot()
    counts = (
        f"{len(snap['prompts'])} probe entries, {len(snap['mapping'])} mapped trials, "
        f"{len(snap['index'])} index tables, "
        f"{len(snap['review'])} review outputs, {len(snap['sheets'])} sheets"
    )
    if args.out:
        with open(args.out, "w") as handle:
            json.dump(snap, handle, indent=1, sort_keys=True)
        print(f"snapshot written to {args.out}: {counts}")
        return 0
    with open(args.compare) as handle:
        found = differences(snap, json.load(handle))
    for line in found:
        print(f"DIFFERS {line}")
    print(f"{'unchanged' if not found else f'{len(found)} differences'}: {counts}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
