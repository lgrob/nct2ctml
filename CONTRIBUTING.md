# Contributing

How to change this repository without breaking what it guarantees: that a
mapped trial can be traced to what produced it, that the reference data is
what `ref/SOURCES.tsv` says it is, and that a released index can be rebuilt
from its tag. Setup is in the [README](README.md#quickstart).

## Tests

```bash
python -m unittest discover -s tests -t . -v       # offline suite
python -m unittest tests.test_reference_validation -v
```

Run it from the repository root with `-t .`: the suite then loads
`tests/__init__.py`, which wraps the LLM platform so that any test reaching
it fails instead of sending a request (`tests/support.py`). Without `-t .`,
`tests/test_offline_guard.py` fails and says so.

The two live-model tests are skipped by default; they send real prompts to the
backend `config.py` selects, so they need a running server or an API key:

```bash
RUN_LIVE_LLM_TESTS=1 python -m unittest tests.test_ai_helper -v
```

GitHub Actions runs the suite on Python 3.12 and 3.13 on every push
(`.github/workflows/tests.yml`), installed from `requirements.lock` and
`requirements-dev.txt`. The job also runs the benchmark regression check
(`bench/README.md`). `cache/` is not in git, so CI uses frozen
ClinicalTrials.gov records from `tests/fixtures/registry/nct`. Tests that
need CTIS records skip there: whether those may be republished is not
settled (`tests/fixtures/registry/README.md`).

A test that needs trial data skips when it is missing rather than failing,
and says why in the skip message. Never write a test that calls the live
API or writes to `cache/`, `ctml/` or `runs/` unguarded; the suite must be
safe to run anywhere, as often as anyone likes.

## Linting and formatting

[ruff](https://docs.astral.sh/ruff/) lints and formats the code (its
formatter replaces Black). The rules are in `pyproject.toml`, and the version
is pinned in `requirements-dev.txt`, because a different ruff can format
differently. GitHub Actions runs both checks on every push and pull request
(`.github/workflows/lint.yml`).

```bash
./.venv/bin/pip install -r requirements-dev.txt
ruff check .                  # lint; --fix applies the safe fixes
ruff format .                 # format in place; --check only reports
pip install pre-commit && pre-commit install   # run both on every commit
git config blame.ignoreRevsFile .git-blame-ignore-revs   # blame past the reformat
```

## Types

mypy checks `src/`, `utils/`, `bench/`, `scripts/`, `main.py` and
`config.py` (settings in `pyproject.toml`), in CI's `types` job and
locally:

```bash
./.venv/bin/pip install -r requirements-dev.txt
mypy
```

It is non-strict: a function with annotations has its body checked, and
one without is skipped. The boundaries are annotated, so a wrong argument
there is an error:
- the model transport (`utils.llm.transport.send_ai_request`,
  `parse_ai_response`);
- the shared mapping (`src/mapping/`);
- the mapper's rules (`src/text_rules.py`);
- the index rows, as TypedDicts in `utils/build_trial_index.py`. The column
  lists are derived from them, so a new column is added to the row type.

Annotate what you add, at least its signature. Turning on
`check_untyped_defs` would check every function; it reports 136 findings
today, 43 of them in `utils/provenance.py`. That is the next step, not a
requirement yet.

## Linting notes

Trailing whitespace inside the prompt strings of `utils/llm/prompts/` is
deliberately left alone (`W291`/`W293` are ignored): removing it would change
what the model is asked.

## Changing a prompt, the model or a mapping rule

Anything that can change what the pipeline maps needs numbers before it is
the default. The rule used so far:

1. Put the new behaviour behind a setting (as `GENOMIC_PROMPT` and
   `DIAGNOSIS_INPUT` are) and leave the default alone.
2. Measure both arms on the same trials, with replicates for anything that
   goes through the model: the benchmark (`bench/`) for diagnoses, genes and
   ages, or a labelled set for the question at hand. Report recall and
   precision separately, per trial, not only the means. A precision gain is
   not adopted at the cost of curated diagnoses (recall first).
3. Write the result up in [doc/decisions/](doc/decisions/README.md), using
   its template. Then change the default, in the same commit as the decision
   file, and name the file in the `config.py` comment.
4. If the deterministic diagnosis floor changed,
   `python -m bench.conditions_baseline` fails. Check the per-trial
   differences it prints, then accept them with `--update` in the same
   commit.

A mapping run you will cite gets a file in [doc/runs/](doc/runs/README.md).
Keep its `runs/<run_id>/` directory: it is the only copy of what the model
answered, and `LLM_PLATFORM=Replay` can rebuild the run from it
([doc/provenance.md](doc/provenance.md)).

## Changing reference data

Every file in `ref/` is listed in `ref/SOURCES.tsv`
([doc/reference_data.md](doc/reference_data.md)).

- **Curated files** (synonym tables, overrides, translocations): edit, and
  say why in the commit and, where the file has one, in its reason column.
- **Pinned files** (Oncotree, MANE, NCBI synonyms, the gene panel) change
  only through their fetch or build step. Then re-pin in the same commit:

  ```bash
  python -m utils.verify_refs --fetch-oncotree <version>   # or the file's build script
  python -m utils.verify_refs --update ref/<file>
  python -m unittest discover -s tests -t .
  ```

  For Oncotree, also update the version where the docs name it
  (`tests/test_oncotree.py` checks this).
- **A new file** needs a row in `ref/SOURCES.tsv`, or CI fails.

Files that are already mapped keep the hashes they were mapped against. The
index manifest's `reference_drift` counts how many trials are behind.

## Releasing the index

An index a report cites is a release, never `index/`:
`python -m utils.release_index create` on a clean, committed checkout, then
push the tag and store the archive
([doc/index_guide.md](doc/index_guide.md#index-releases)).

## Merging upstream

The whole repository was reformatted in one commit, listed in
`.git-blame-ignore-revs`. GitHub's blame skips it automatically. A plain
merge from upstream would now conflict almost everywhere, so merge upstream
with:

```bash
python scripts/merge_upstream.py              # upstream/main, or pass a ref
```

It merges each file three ways after putting both the merge base and
upstream's version through the same ruff steps, so only real changes can
conflict. On a simulated upstream update touching three files, a plain merge
conflicted in 2 files, formatting upstream's tip alone conflicted in 24, and
the script conflicted in 1: the function both sides had really changed. A
conflict leaves the merge in progress, with the files unstaged, for you to
resolve.

A file modified from upstream carries the Kispi notice at the top (Apache-2.0
§4(b)); add it when you first change an upstream file, and say what differs
in [CHANGES.md](CHANGES.md).

## Recording changes

- A code change: an entry at the top of [doc/changelog.md](doc/changelog.md),
  saying what changed, why, and what was checked.
- A measured choice: a file in [doc/decisions/](doc/decisions/).
- A run or a review-queue audit: a file in [doc/runs/](doc/runs/).
- A new difference from upstream worth a reader's attention: a line in
  [CHANGES.md](CHANGES.md).
- A problem found but not fixed: [doc/open_issues.md](doc/open_issues.md),
  with what it costs.

Commit per step, with the numbers in the message, and the offline suite green
on the committed tree.
