"""
Freeze the flat index as a numbered release that a report can cite.

    python -m utils.release_index create [--version index-2026.10.01]
    python -m utils.release_index verify releases/index-2026.10.01.tar.gz [--rebuild]

Why
---
`sync_trials.sh` rebuilds index/ on every run and overwrites it, index/ is
not in git, and by default it includes machine output nobody has reviewed.
So an index that informed a patient report is gone by the next run, and it
cannot be rebuilt, because its inputs in cache/ were not kept. A release
fixes that for the indexes that matter:

- built from ctml/reviewed only, with --strict (a protein change that fails
  its reference check stops the build), so it rests on nothing unreviewed;
- built from a clean checkout, so every input - code, ref/, ctml/reviewed,
  ref/scope_overrides.tsv - is in the commit, and the commit is tagged;
- packed with release.json (commit, input and output SHA-256) into a
  reproducible releases/<tag>.tar.gz, whose SHA-256 the tag message records.

A report cites the release tag. `verify` checks an archive against its own
hashes; `--rebuild` also builds again from the tagged commit, in a
temporary worktree, and requires byte-identical outputs - the proof that
the release is reproducible, not just stored.

`create` only tags locally. Publishing is a separate, deliberate step: push
the tag, and store the archive somewhere permanent (a GitHub Release, or
Kispi storage); the commands are printed.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RELEASES = "releases"
PREFIX = "index-"
SOURCE = "ctml/reviewed"
OUTPUTS = ("trials.tsv", "trial_diagnosis.tsv", "trial_genomic.tsv", "layer_conflicts.tsv")
RELEASE_FILE = "release.json"


def git(*args, root=ROOT, check=True):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as handle:
        return sha256_bytes(handle.read())


def next_version(today=None, root=ROOT):
    """index-YYYY.MM.DD, then .2, .3, ... for further releases that day."""
    base = f"{PREFIX}{(today or datetime.now(UTC)):%Y.%m.%d}"
    taken = set(git("tag", "--list", f"{base}*", root=root).split())
    if base not in taken:
        return base
    n = 2
    while f"{base}.{n}" in taken:
        n += 1
    return f"{base}.{n}"


def preflight(root=ROOT):
    """Reasons not to release from `root`; empty when it is clean and its reference data checks."""
    problems = []
    # Not .strip(): the first status column may be a space, and the path starts at column 3.
    lines = [line for line in git("status", "--porcelain", root=root).splitlines() if line]
    if lines:
        problems.append(
            f"working tree not clean ({len(lines)} changed or untracked: "
            f"{', '.join(line[3:] for line in lines[:5])}{' ...' if len(lines) > 5 else ''}); "
            f"a release must be rebuildable from its commit"
        )
    refs = subprocess.run(
        [sys.executable, "-m", "utils.verify_refs"], cwd=root, capture_output=True, text=True
    )
    if refs.returncode != 0:
        problems.append("reference data does not match ref/SOURCES.tsv:\n" + refs.stdout.strip())
    return problems


def build(out_dir, root=ROOT):
    """Build the reviewed-only strict index of `root` into out_dir; returns its manifest."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "utils.build_trial_index",
            "--source",
            SOURCE,
            "--strict",
            "--out",
            out_dir,
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"index build failed:\n{result.stdout}\n{result.stderr}")
    with open(os.path.join(out_dir, "manifest.json")) as handle:
        return json.load(handle)


def reviewed_hashes(root=ROOT):
    directory = os.path.join(root, SOURCE)
    return {
        f"{SOURCE}/{name}": sha256_file(os.path.join(directory, name))
        for name in sorted(os.listdir(directory))
        if name.endswith((".yaml", ".yml", ".json"))
    }


def archive_bytes(members):
    """A tar.gz of {name: bytes} that depends only on the names and contents."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(members):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(members[name]), 0, 0o644
            tar.addfile(info, io.BytesIO(members[name]))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def create(version=None, root=ROOT, today=None):
    problems = preflight(root)
    if problems:
        sys.exit("Not releasing:\n- " + "\n- ".join(problems))
    commit = git("rev-parse", "HEAD", root=root).strip()
    version = version or next_version(today, root)
    if not version.startswith(PREFIX):
        sys.exit(f"a release tag starts with {PREFIX!r}")
    if git("tag", "--list", version, root=root).strip():
        sys.exit(f"tag {version} already exists")

    with tempfile.TemporaryDirectory() as out:
        manifest = build(out, root)
        members = {}
        for name in (*OUTPUTS, "manifest.json"):
            with open(os.path.join(out, name), "rb") as handle:
                members[f"{version}/{name}"] = handle.read()
    release = {
        "release": version,
        "commit": commit,
        "created_at": (today or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.split()[0],
        "source": SOURCE,
        "strict": True,
        "trials": manifest["trials"],
        "outputs": {name: manifest["outputs"][name] for name in OUTPUTS},
        "reference_sha256": manifest["reference_sha256"],
        "reviewed_ctml_sha256": reviewed_hashes(root),
        "verify": f"python -m utils.release_index verify {RELEASES}/{version}.tar.gz --rebuild",
    }
    members[f"{version}/{RELEASE_FILE}"] = (
        json.dumps(release, indent=2, sort_keys=True) + "\n"
    ).encode()
    data = archive_bytes(members)
    digest = sha256_bytes(data)

    os.makedirs(os.path.join(root, RELEASES), exist_ok=True)
    archive = os.path.join(root, RELEASES, f"{version}.tar.gz")
    with open(archive, "wb") as handle:
        handle.write(data)
    with open(archive + ".sha256", "w") as handle:
        handle.write(f"{digest}  {version}.tar.gz\n")

    outputs = "\n".join(
        f"  {n}  {v['rows']} rows  {v['sha256']}" for n, v in release["outputs"].items()
    )
    message = (
        f"Trial index release {version}\n\n"
        f"Built from {SOURCE} at this commit with --strict: {release['trials']} trials.\n"
        f"Archive {version}.tar.gz sha256 {digest}\n\n{outputs}\n"
    )
    git("tag", "-a", version, "-m", message, commit, root=root)
    return version, archive, digest


def _extract(archive):
    with tarfile.open(archive, "r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}


def verify(archive, rebuild=False, root=ROOT):
    """Problems with a release archive, as messages; empty when it checks out."""
    problems = []
    sidecar = archive + ".sha256"
    if os.path.exists(sidecar):
        with open(sidecar) as handle:
            expected = handle.read().split()[0]
        if sha256_file(archive) != expected:
            problems.append(
                f"{os.path.basename(archive)} does not match {os.path.basename(sidecar)}"
            )
    members = _extract(archive)
    (release_name,) = [n for n in members if n.endswith("/" + RELEASE_FILE)]
    version = release_name.split("/")[0]
    release = json.loads(members[release_name])
    for name, info in release["outputs"].items():
        data = members.get(f"{version}/{name}")
        if data is None:
            problems.append(f"{name} missing from the archive")
        elif sha256_bytes(data) != info["sha256"]:
            problems.append(f"{name} differs from the SHA-256 in {RELEASE_FILE}")

    tagged = git("rev-list", "-n", "1", version, root=root, check=False).strip()
    if not tagged:
        problems.append(f"tag {version} not found here (git fetch --tags?)")
    elif tagged != release["commit"]:
        problems.append(
            f"tag {version} points to {tagged[:12]}, the release to {release['commit'][:12]}"
        )
    else:
        # The tag message is the one record not stored beside the archive, so
        # an archive rewritten together with its .sha256 and release.json
        # still fails here.
        message = git("tag", "--list", "--format=%(contents)", version, root=root)
        recorded = next((w for w in message.split() if len(w) == 64), None)
        if recorded != sha256_file(archive):
            problems.append(f"archive does not match the SHA-256 recorded in tag {version}")

    if rebuild and not problems:
        with tempfile.TemporaryDirectory() as tmp:
            tree, out = os.path.join(tmp, "tree"), os.path.join(tmp, "out")
            git("worktree", "add", "--detach", "--quiet", tree, release["commit"], root=root)
            try:
                build(out, tree)
                if reviewed_hashes(tree) != release["reviewed_ctml_sha256"]:
                    problems.append(
                        f"{SOURCE} at {release['commit'][:12]} differs from the release"
                    )
                for name, info in release["outputs"].items():
                    if sha256_file(os.path.join(out, name)) != info["sha256"]:
                        problems.append(f"rebuilt {name} differs from the release")
            finally:
                git("worktree", "remove", "--force", tree, root=root, check=False)
    return version, release, problems


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="build, pack and tag a release from a clean checkout")
    c.add_argument("--version", help=f"release tag (default {PREFIX}YYYY.MM.DD[.N])")
    v = sub.add_parser("verify", help="check an archive; --rebuild also rebuilds from its commit")
    v.add_argument("archive")
    v.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)

    if args.command == "create":
        version, archive, digest = create(args.version)
        rel = os.path.relpath(archive, ROOT)
        print(f"Released {version}: {rel}\n  sha256 {digest}\n  tagged locally at HEAD\n")
        print("To publish (nothing has left this machine yet):")
        print(f"  git push origin {version}")
        print(f"  gh release create {version} {rel} {rel}.sha256 --notes-from-tag")
        print("  or copy the archive and its .sha256 to permanent Kispi storage.")
        print(f"\nCite {version} in reports. Check it any time with:")
        print(f"  python -m utils.release_index verify {rel} --rebuild")
        return 0

    version, release, problems = verify(args.archive, args.rebuild)
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        return 1
    how = "rebuilt from its commit, byte-identical" if args.rebuild else "hashes match"
    print(f"{version}: {release['trials']} trials, commit {release['commit'][:12]}; {how}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
