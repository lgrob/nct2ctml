# Reviewing flagged trials

How a curator works through `ctml/needs-review` and accepts a trial into `ctml/reviewed`. Moved from the README on 2026-09-28.

## The review interface

```
./.venv/bin/python -m utils.review.app        # then open http://127.0.0.1:8765
```

Like every other command here it needs the repo's own environment, from the repo
root. The system Python stops with `No module named 'loguru'`; the app says so and
gives this line.

One page per trial: the same evidence the static sheets show, an editor for the
trial's CTML, and the decision. **Save and re-check** writes the file, keeps the
previous version as `<trial>.yaml.prev` and re-runs the review gate, so the page
tells you what `accept` would still refuse before you press it. **Accept** and
**Exclude** are `gate.accept` and `gate.exclude` — the same code as the command
line, so `ctml/review_log.tsv` and the accepted file's SHA-256 are written
exactly as before, and a file that still carries a flag is still refused.

A reviewer name is required for both decisions; Exclude also needs the note,
which becomes the reason in `ref/scope_overrides.tsv`. The server binds
127.0.0.1 only — the queue is unpublished clinical mapping output — handles one
request at a time, and has no authentication because it is not reachable off the
machine. Two curators should not point it at the same checkout: there is no
locking, so the second save would overwrite the first.

Nothing here is a new rule. The static sheets (`review_helper sheets`) and the
CLI still work unchanged; the interface exists so that resolving a flag does not
mean a text editor in one window and a terminal in another.

`python -m utils.review_helper` (code in `utils/review/`; the rules it shares
with the mapper are in `src/text_rules.py`) puts the evidence for each flag next to the flag and
makes accepting a reviewed trial a checked, logged step. It reads the same
reference data as the mapper and never calls a model. Run it from the repo
root with the repo's environment (`source .venv/bin/activate`, or call
`./.venv/bin/python` directly); a Python without the repo's requirements
fails with `No module named 'loguru'`.

```
python -m utils.review_helper queue                      # ctml/needs-review with reasons
python -m utils.review_helper sheets                     # one HTML sheet per queued trial
python -m utils.review_helper audit --n 60               # random mapped trials (roadmap 3.4)
python -m utils.review_helper check NCT05843253          # what accept would still refuse
python -m utils.review_helper accept NCT05843253 --reviewer <name> [--note "..."]
python -m utils.review_helper exclude NCT05843253 --reviewer <name> --reason "..."
python -m utils.review_helper flag-exclusions [--apply]  # see below
python -m utils.review_helper flag-gene-status [--apply] # genes required although the text says absent
```

**Excluded diagnoses.** Write `oncotree_primary_diagnosis: '!Name'` (quoted:
a bare leading `!` is a YAML tag) beside the diagnosis a trial enrols to
exclude a subtype, e.g. AML without APL. The index publishes the excluded node
and its descendants with `include = 0` and leaves them out of the eligible
rows. `accept` refuses a trial whose only diagnoses are excluded ones.

**Diagnoses named only in the exclusion criteria** (`diagnosis_excluded`).
The mapper flags a diagnosis that the exclusion criteria name and that the
inclusion criteria, title and conditions do not, and routes the trial to
review. `flag-exclusions` applies the same check to CTML already written;
with `--apply` it adds the flag and moves mapped trials to the review queue.
`ctml/reviewed` is never touched.

`exclude` takes a trial out of scope: it adds a `skip` row with the reason to
`ref/scope_overrides.tsv` and logs it in `ctml/review_log.tsv`. `map --all`
then no longer maps the trial, and the index build drops it from every layer
(listed under `excluded_by_scope_override` in `manifest.json`). Its YAML files
stay where they are. Rebuild the index to apply it.

Open `review_sheets/index.html` (git-ignored). Each sheet lists every flag with
what resolves it and the passages that mention the item. For a flagged gene
the sheet says which of these applies: named in the trial text but not in the
arm's criteria (the mapper checks each arm's own text), only an ambiguous NCBI
alias (such as ALL for BCR, shown but never counted as support), only a
near-miss spelling (KTM2A), or not named at all. Diagnoses are marked as named
in the text, parent named, or not named. Protein changes show the residue the
reference protein carries.

To resolve a trial, edit its YAML in `ctml/needs-review/`: delete a flag key
to confirm its item, or delete the item. Then run `accept`. It refuses a file
that still carries a flag, has no diagnosis, names a gene or diagnosis outside
the reference data, or has a protein change that fails its reference check.
On success it stamps `curated_on`, moves the file to `ctml/reviewed/` and
appends a line to `ctml/review_log.tsv`: date, trial, reviewer, the flags
resolved and the file's SHA-256. The audit command writes
`ctml/audit_<date>.tsv` for the verdicts, and sheets to `review_sheets/audit/`.
