"""
Merge upstream (sumedhasaxena/nct2ctml) without the conflicts the ruff
reformat would otherwise cause.

    python scripts/merge_upstream.py                 # upstream/main
    python scripts/merge_upstream.py <ref>           # any other upstream commit

This fork was reformatted with ruff and upstream was not. A plain merge
therefore conflicts wherever upstream changed a line whose layout changed
here. Formatting only upstream's tip is worse: the merge base stays
unformatted, so every line this fork edited conflicts with a formatting
change.

So each file upstream changed is merged three ways with BOTH the base and
upstream's version put through the same ruff steps as the reformat commit
(check --fix, format, check --fix; same version, same pyproject.toml).
Upstream's side of the merge then carries only what upstream changed, and
what conflicts is what both sides really changed. The result is recorded as
an ordinary merge of <ref>, so upstream's history is kept and nothing needs
adding to .git-blame-ignore-revs.

For a conflict in a Python file, the report also names, for each function
upstream changed, the file of this fork that defines it now, so a fix to a
function step 11 moved out of clinical_trials_gov.py or ai_helper.py can be
carried to its new home.

When anything conflicts the merge is left in progress: conflicted files hold
the usual markers and are NOT staged. Resolve them, `git add` them and
`git commit`, or `git merge --abort`. Python files the merge completed are
formatted again, since joining hunks can leave a line out of format.
"""

import argparse
import ast
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUFF = os.environ.get("RUFF", "ruff")
# The steps of the reformat commit, in its order.
RUFF_STEPS = (
    ["check", "--fix", "--exit-zero", "--quiet"],
    ["format", "--quiet"],
    ["check", "--fix", "--exit-zero", "--quiet"],
)


def run(*cmd, data=None, check=True):
    result = subprocess.run(cmd, cwd=ROOT, input=data, capture_output=True)
    if check and result.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed:\n{result.stderr.decode(errors='replace')}")
    return result


def git(*args, **kwargs):
    return run("git", *args, **kwargs)


def show(rev, path):
    """The file at `rev`, or None where it does not exist."""
    result = git("show", f"{rev}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None


def formatted(path, data):
    """`data` as the reformat commit would have left it; unchanged if not Python or not parseable."""
    if data is None or not path.endswith(".py"):
        return data
    probe = [RUFF, "format", "--quiet", "--force-exclude", "--stdin-filename", path, "-"]
    if run(*probe, data=data, check=False).returncode != 0:
        print(f"  {path}: not valid Python, merged unformatted")
        return data
    for step in RUFF_STEPS:
        data = run(RUFF, *step, "--force-exclude", "--stdin-filename", path, "-", data=data).stdout
    return data


def merge_text(ours, base, theirs):
    """(merged, conflicts) from git merge-file; base may be empty."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, data in (("ours", ours), ("base", base or b""), ("theirs", theirs)):
            paths.append(os.path.join(tmp, name))
            with open(paths[-1], "wb") as handle:
                handle.write(data)
        result = git(
            "merge-file",
            "-p",
            "-L",
            "this fork",
            "-L",
            "base (formatted)",
            "-L",
            "upstream (formatted)",
            *paths,
            check=False,
        )
    if result.returncode < 0 or result.returncode > 127:
        sys.exit(f"git merge-file failed: {result.stderr.decode(errors='replace')}")
    return result.stdout, result.returncode


def write(path, data):
    full = os.path.join(ROOT, path)
    if data is None:
        if os.path.exists(full):
            git("rm", "--quiet", "--", path)
        return
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, "wb") as handle:
        handle.write(data)


def _top_level(source):
    """{name: source text} of the top-level functions and classes, {} if unparseable."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    return {
        n.name: ast.get_source_segment(source, n)
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def changed_functions(base_source, tip_source):
    """Top-level functions and classes upstream added, changed or removed, sorted."""
    before, after = _top_level(base_source or ""), _top_level(tip_source or "")
    return sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))


def where_now(names):
    """{name: [files in this fork that define it at top level]}."""
    found = {n: [] for n in names}
    files = git("ls-files", "*.py").stdout.decode().split()
    for f in files:
        with open(os.path.join(ROOT, f), encoding="utf-8") as handle:
            defined = _top_level(handle.read())
        for n in names:
            if n in defined:
                found[n].append(f)
    return found


def moved_hints(path, base, tip):
    """
    Lines saying where each function upstream changed in `path` lives now.
    Step 11 moved much of clinical_trials_gov.py and ai_helper.py into other
    modules, so an upstream fix to a moved function has to be carried there by
    hand; this names the file.
    """
    if not path.endswith(".py"):
        return []
    decode = lambda b: b.decode("utf-8", "replace") if b else ""  # noqa: E731
    names = changed_functions(decode(show(base, path)), decode(show(tip, path)))
    lines = []
    for name, files in where_now(names).items():
        if files == [path]:
            continue
        where = ", ".join(files) if files else "nowhere here (removed, or renamed)"
        lines.append(f"      upstream changed {name}(): now in {where}")
    return lines


def merge_file(path, base, tip):
    """Merge one path upstream changed into the worktree. Returns a conflict description or None."""
    full = os.path.join(ROOT, path)
    ours = open(full, "rb").read() if os.path.exists(full) else None
    b, t = formatted(path, show(base, path)), formatted(path, show(tip, path))
    if ours in (b, t) or b == t:
        # Unchanged here (take upstream's), or already the same, or upstream's
        # change vanished under formatting (keep ours).
        result = t if ours == b else ours
        write(path, result)
        if result is not None:
            git("add", "--", path)
        return None
    if ours is None:
        write(path + ".upstream", t)
        return "deleted here, changed upstream; upstream's version is in .upstream"
    if t is None:
        return "changed here, deleted upstream; kept this fork's version"
    if b"\0" in ours + (b or b"") + t:
        write(path + ".upstream", t)
        return "binary, changed on both sides; upstream's version is in .upstream"
    merged, conflicts = merge_text(ours, b, t)
    if not conflicts:
        merged = formatted(path, merged)
    write(path, merged)
    if conflicts:
        return f"{conflicts} conflicting hunk(s)"
    git("add", "--", path)
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("ref", nargs="?", default="upstream/main")
    args = ap.parse_args()

    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        sys.exit("Commit or stash your changes first.")
    with open(os.path.join(ROOT, "requirements-dev.txt")) as handle:
        want = next(line.split("==")[1].strip() for line in handle if line.startswith("ruff=="))
    have = run(RUFF, "--version").stdout.decode().split()[1]
    if want != have:
        sys.exit(
            f"{RUFF} is {have} but requirements-dev.txt pins {want}, and a different "
            f"version can format differently: pip install -r requirements-dev.txt"
        )

    if args.ref.startswith("upstream/"):
        git("fetch", "upstream")
    tip = git("rev-parse", "--verify", f"{args.ref}^{{commit}}").stdout.decode().strip()
    short = tip[:7]
    if git("merge-base", "--is-ancestor", tip, "HEAD", check=False).returncode == 0:
        print(f"{args.ref} ({short}) is already merged.")
        return 0
    base = git("merge-base", "HEAD", tip).stdout.decode().strip()
    changed = git("diff", "--name-only", "--no-renames", "-z", base, tip).stdout.decode()
    paths = [p for p in changed.split("\0") if p]
    print(f"Merging {args.ref} ({short}): {len(paths)} files changed upstream since {base[:7]}")

    # Record the merge with upstream as second parent; the content is ours
    # until each changed path is merged below.
    message = f"Merge upstream {short} (three-way on ruff-formatted base and tip)"
    git("merge", "--no-commit", "--no-ff", "-s", "ours", "-m", message, tip)
    conflicts = {}
    for path in paths:
        problem = merge_file(path, base, tip)
        if problem:
            conflicts[path] = problem

    if conflicts:
        print("\nConflicts (not staged):")
        for path, problem in conflicts.items():
            print(f"  {path}: {problem}")
            for line in moved_hints(path, base, tip):
                print(line)
        print("\nResolve them, `git add` each, then `git commit`; or `git merge --abort`.")
        return 1
    git("commit", "--quiet", "-m", message)
    print(f"Merged {args.ref} with no conflicts. Run the tests before pushing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
