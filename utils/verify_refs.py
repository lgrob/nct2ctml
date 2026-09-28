"""
Check the reference data in ref/ against ref/SOURCES.tsv.

    python -m utils.verify_refs                        # offline: listed, present, unchanged
    python -m utils.verify_refs --online               # also compare Oncotree with its API
    python -m utils.verify_refs --update ref/mane_genes.tsv  # re-pin after a rebuild
    python -m utils.verify_refs --fetch-oncotree oncotree_2025_10_03 [--out PATH]

Offline, it fails when a file in ref/ is not listed in SOURCES.tsv, when a
listed file is missing, or when a pinned file's SHA-256 has changed. A
pinned file (kind fetched, built or supplied) should change only through
its fetch or build step, so a changed hash is either that step, which is
re-pinned with --update in the same commit, or a silent replacement, which
is what this catches. Curated files are not pinned; git records their edits.

--online fetches the Oncotree version SOURCES.tsv names and compares the
tree: every node's code, name and place in the hierarchy. The API does not
serve a version byte for byte the same over time (see SOURCES.tsv), so
differences in the metadata columns are reported but do not fail the check.

--fetch-oncotree writes an Oncotree version in the layout of
ref/oncotree_file.txt, every row padded to six level columns. It is the
fetch step for that file: an upgrade is fetch, --update, then the tests
(tests/test_oncotree.py pins the node count and the documented version).

Standard library only, so it runs before anything is installed.
"""

import argparse
import csv
import hashlib
import os
import ssl
import subprocess
import sys
import urllib.request
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOURCES = "ref/SOURCES.tsv"
PINNED_KINDS = {"fetched", "built", "supplied"}
KINDS = PINNED_KINDS | {"curated"}
ONCOTREE_FILE = "ref/oncotree_file.txt"
ONCOTREE_API = "https://oncotree.mskcc.org/api/tumor_types.txt?version={version}"
LEVELS = 6
# Kept in ref/ locally but never committed (.gitignore says why).
LOCAL_ONLY = {"ref/Census_gene_list.csv", "ref/.ncbi_gene_cache.json"}


def load_sources(path=SOURCES):
    with open(os.path.join(ROOT, path), encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        return {row["file"]: row for row in rows}


def sha256(path):
    digest = hashlib.sha256()
    with open(os.path.join(ROOT, path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_in_ref():
    """The files of ref/ that belong in the repository: tracked ones, or on disk without git."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "ref"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
        if listed:
            return sorted(listed)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for name in os.listdir(os.path.join(ROOT, "ref")):
        path = f"ref/{name}"
        if os.path.isfile(os.path.join(ROOT, path)) and path not in LOCAL_ONLY:
            if not name.endswith(".generated.tsv"):
                found.append(path)
    return sorted(found)


def check(sources=None):
    """Problems found offline, as messages; empty when everything matches."""
    sources = load_sources() if sources is None else sources
    problems = []
    for path in files_in_ref():
        if path != SOURCES and path not in sources:
            problems.append(f"{path}: in ref/ but not listed in {SOURCES}")
    for path, row in sources.items():
        kind = row["kind"]
        if kind not in KINDS:
            problems.append(f"{path}: unknown kind {kind!r}")
            continue
        if not os.path.isfile(os.path.join(ROOT, path)):
            problems.append(f"{path}: listed in {SOURCES} but missing")
            continue
        if kind in PINNED_KINDS:
            if not row["sha256"]:
                problems.append(f"{path}: kind {kind} but no sha256 pinned")
            elif sha256(path) != row["sha256"]:
                problems.append(
                    f"{path}: SHA-256 {sha256(path)[:12]} differs from the pinned "
                    f"{row['sha256'][:12]}. If it was rebuilt on purpose, run "
                    f"python -m utils.verify_refs --update {path}"
                )
    return problems


def update(paths, today=None):
    """Re-pin `paths` with their current SHA-256 and today's date, keeping the file's comments."""
    today = today or date.today().isoformat()
    full = os.path.join(ROOT, SOURCES)
    with open(full, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    header = next(line for line in lines if line and not line.startswith("#")).split("\t")
    col = {name: i for i, name in enumerate(header)}
    remaining = set(paths)
    for i, line in enumerate(lines):
        fields = line.split("\t")
        if fields[0] in remaining:
            if fields[col["kind"]] not in PINNED_KINDS:
                sys.exit(f"{fields[0]} is {fields[col['kind']]}, not pinned; nothing to update")
            fields[col["sha256"]] = sha256(fields[0])
            fields[col["retrieved"]] = today
            lines[i] = "\t".join(fields)
            remaining.discard(fields[0])
    if remaining:
        sys.exit(f"not in {SOURCES}: {', '.join(sorted(remaining))}")
    with open(full, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def oncotree_rows(text):
    """
    (levels, metadata) per row of an Oncotree tab export, in either layout:
    padded to six level columns (ref/oncotree_file.txt) or with the empty
    levels left out (the API). The last five columns are always metadata.
    """
    lines = text.rstrip("\n").split("\n")
    rows = []
    for line in lines[1:]:
        fields = line.rstrip("\r").split("\t")
        rows.append((tuple(f for f in fields[:-5] if f), tuple(fields[-5:])))
    return lines[0].rstrip("\r"), rows


def fetch_oncotree(version):
    # python.org's macOS build has no CA bundle until "Install Certificates" is
    # run; certifi (installed with anthropic) provides one. Otherwise the
    # system store, which is what CI uses.
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    url = ONCOTREE_API.format(version=version)
    with urllib.request.urlopen(url, timeout=60, context=context) as response:
        return response.read().decode("utf-8")


def padded(text):
    """An Oncotree export in the layout of ref/oncotree_file.txt."""
    header, rows = oncotree_rows(text)
    out = [header]
    for levels, meta in rows:
        out.append("\t".join(list(levels) + [""] * (LEVELS - len(levels)) + list(meta)))
    return "\n".join(out) + "\n"


def compare_oncotree(local_text, remote_text):
    """(tree differences, metadata differences) between two exports, as messages."""
    local_header, local = oncotree_rows(local_text)
    remote_header, remote = oncotree_rows(remote_text)
    tree = []
    if local_header != remote_header:
        tree.append("header differs")
    local_meta, remote_meta = dict(local), dict(remote)
    for levels in sorted(set(local_meta) - set(remote_meta)):
        tree.append(f"only in ref/: {' > '.join(levels)}")
    for levels in sorted(set(remote_meta) - set(local_meta)):
        tree.append(f"only upstream: {' > '.join(levels)}")
    meta = [
        f"{levels[-1]}: {local_meta[levels]} here, {remote_meta[levels]} upstream"
        for levels in sorted(set(local_meta) & set(remote_meta))
        if local_meta[levels] != remote_meta[levels]
    ]
    return tree, meta


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--online", action="store_true", help="also compare Oncotree with its API")
    ap.add_argument("--update", nargs="+", metavar="FILE", help="re-pin these files")
    ap.add_argument("--fetch-oncotree", metavar="VERSION", help="write this Oncotree version")
    ap.add_argument("--out", default=ONCOTREE_FILE, help="where --fetch-oncotree writes")
    args = ap.parse_args(argv)

    if args.fetch_oncotree:
        text = padded(fetch_oncotree(args.fetch_oncotree))
        with open(os.path.join(ROOT, args.out), "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {args.fetch_oncotree} to {args.out}; run --update {args.out} if it is ref/")
        return 0
    if args.update:
        update(args.update)
        print(f"re-pinned {', '.join(args.update)}")

    sources = load_sources()
    problems = check(sources)
    if args.online:
        version = sources[ONCOTREE_FILE]["version"]
        with open(os.path.join(ROOT, ONCOTREE_FILE), encoding="utf-8") as handle:
            tree, meta = compare_oncotree(handle.read(), fetch_oncotree(version))
        problems += [f"{ONCOTREE_FILE} vs {version}: {m}" for m in tree]
        for m in meta:
            print(f"note: {ONCOTREE_FILE} vs {version} metadata: {m}")
        if not tree:
            print(f"{ONCOTREE_FILE}: tree identical to {version} from the API")

    for problem in problems:
        print(f"FAIL {problem}")
    pinned = sum(row["kind"] in PINNED_KINDS for row in sources.values())
    if not problems:
        print(f"ref/: {len(sources)} files listed, {pinned} pinned, all match {SOURCES}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
