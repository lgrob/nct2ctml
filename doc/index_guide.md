# The flat query index

What `utils/build_trial_index.py` publishes, how a downstream pipeline joins against it, and how an index a report cites is released. Moved from the README on 2026-09-28.

CTML is a nested boolean tree, and "does this tree match sample X" cannot be
answered by a query over nested JSON. `utils/build_trial_index.py` flattens the
CTML once, at build time, so a downstream pipeline needs only an equi-join:

```bash
python -m utils.build_trial_index                          # every mapped trial, with review status
python -m utils.build_trial_index --source ctml/reviewed   # reviewed trials only
python -m utils.build_trial_index --strict                 # fail on any unverified protein change
```

By default the index reads three layers, a later one replacing an earlier one
for the same trial: `cache/ctml` (`mapped`), `ctml/needs-review`
(`needs_review`) and `ctml/reviewed` (`reviewed`). `trials.tsv` carries
`review_status`, `reviewed` (0/1) and `source_file`, so a hit on an unreviewed
trial can be routed to a curator rather than into a report. `--source` builds
from one directory instead; its rows are `reviewed` only if it is
`ctml/reviewed`. `--out` is the output directory (default `index`).

A trial sent to `ctml/needs-review` by one run and mapped cleanly by a later
one keeps its review copy: the mapper never deletes it, because a curator may
be editing it. The index still publishes the review copy, sets
`layer_conflict = newer_mapped_copy` and lists the pair in
`layer_conflicts.tsv`. Resolve it by removing the review copy, or by moving
the curated file to `ctml/reviewed/`. "Newer" is judged by file modification
time, so a copy that resets times can hide a conflict.

When a later run sends a trial to review again and its new mapping differs
from the copy already in `ctml/needs-review`, the old copy is kept as
`<trial>.yaml.prev` (then `.prev.1`, `.prev.2`, ...; a backup is never
overwritten) before the new one is written. The index skips these files and
lists them under `review_backups` in `manifest.json`.

Outputs:

| File | One row per | Key columns |
|---|---|---|
| `trials.tsv` | trial | `trial_id`, `source`, `nct_id`, `phase`, `status`, `review_status`, `reviewed`, `source_file`, `layer_conflict`, `age_min`/`age_max` with `age_min_inclusive`/`age_max_inclusive`, `genes_not_required`, `mapped_at`, `mapped_run`, `mapped_commit`, `llm_model`, `prompt_settings` |
| `trial_diagnosis.tsv` | trial, arm, Oncotree node | `oncotree_code`, `oncotree_name`, `source_term`, `from_basket`, `include` |
| `trial_genomic.tsv` | trial, arm, gene criterion | `hugo_symbol`, `variant_category`, `cnv_call`, `protein_change`, `protein_change_stated`, `protein_change_kind`, `protein_refseq`, `protein_ensembl`, `protein_check`, `fusion_partner`, `fusion`, `fusion_partner_check`, `variant_classification`, `include` |
| `layer_conflicts.tsv` | trial | trials whose published `ctml/needs-review` copy is older than a clean mapping in `cache/ctml`: both files and their modification times |
| `manifest.json` | - | row counts, SHA-256 of each output and of every reference file, the build's commit, `layer_conflicts` count, `review_backups` list, trials per mapping setup and per commit, `reference_drift` |

`genes_not_required` lists genes the text mentions that the model judged not required of every patient (risk group, one cohort, conditional, an alternative route, an example, expression or germline), each with its role. They are not matched on; show them to the clinician beside the trial. Trials carrying only this note are published, not queued for review (roadmap 2.9, option A).

Join samples on `oncotree_code` and `hugo_symbol`. Diagnosis subtrees and the
`_SOLID_`/`_LIQUID_` wildcards are expanded at build time, so a consumer needs
neither the Oncotree hierarchy nor MatchMiner's conventions. Prefer the code to
the display name: codes are stable across Oncotree releases, names are not.
`source_term` keeps the term the curated file states, so a hit can be
explained back to it. The age columns keep the inclusive/exclusive
distinction; the trial-level `age_label` is for display only.

**The index is screening, not decisive.** Rows are the union of everything a
trial could match; exclusions and mixed and/or nesting do not flatten
losslessly. Use the index to narrow the corpus to candidates, then take the
eligibility call from the CTML file, which is the authority. In particular,
`protein_change` is HGVS three-letter notation on the gene's MANE Select
protein (`p.Val600Glu`). That is the same string VEP writes after the
accession in `CSQ_HGVSp`, so it joins on string equality. It is filled only
when `protein_check` is `verified`, meaning every residue it names was found at
that position in `ref/mane_select_proteins.tsv`. Histone H3 is renumbered
from the literature's mature-protein count: `K27M` is `p.Lys28Met`. What the
trial wrote stays in `protein_change_stated`. `--strict` fails the build if
any change does not verify. See `utils/protein_change.py`.

A fusion criterion names its partner when the trial names both genes:
`fusion_partner` and `fusion` in HGNC notation (`EWSR1::FLI1`). The row appears
from both genes' sides when both are panel genes, so match the pair
unordered. An empty partner means any fusion of the gene; a trial listing
example pairs "including but not limited to" keeps its partner-free row too.
Partners are checked against every MANE Select gene plus the IG/TR loci, not
only the panel, because the fusion caller reports off-panel partners such as
RUNX1T1.

`include = 0` rows in `trial_genomic.tsv` are **exclusions** (the CTML
`variant_category` was negated with `!`): a filter that ignores `include`
will report a patient who carries an excluded alteration as a hit.

The build is deterministic - the same inputs give byte-identical outputs - so
the checksums in `manifest.json` identify exactly which trial set produced a
given result. `index/` itself is a working copy: every sync overwrites it,
and by default it includes trials nobody has reviewed. An index a report
cites must be a release.

## Index releases

A release is a frozen, numbered index that can be cited in a report and
rebuilt later from its tag and archive (`utils/release_index.py`):

```bash
python -m utils.release_index create --note "..."     # tag index-YYYY.MM.DD[.N] at HEAD
python -m utils.release_index create --layers reviewed
python -m utils.release_index verify releases/index-2026.10.01.tar.gz --rebuild
```

There are two kinds (`--layers`):

- **`all`, the default since 2026-10-02:** the index of all three layers as
  the pipeline publishes it. The mapped and needs-review CTML and
  `ctml/out-of-scope.tsv` are machine output and not in git, so the archive
  carries them under `<tag>/inputs/`, each with its SHA-256 in
  `release.json`.
  - Such a release rests on unreviewed mapping. Record what is known about
    its error rate with `--note`, for example the latest audit
    ([runs/2026-10-02-3.4-audit.md](runs/2026-10-02-3.4-audit.md)). A report
    citing it treats a match as a lead for a curator, not an eligibility
    decision.
- **`reviewed`:** `ctml/reviewed` only, so everything it rests on is in git
  and curated.

`create` refuses to run unless the checkout is clean (no uncommitted or
untracked files) and `ref/` matches `ref/SOURCES.tsv`. It then:

1. builds the chosen layers with `--strict`;
2. writes `release.json`. It records:
   - the commit and the layers;
   - the note;
   - the review-status counts and the mapping settings per trial;
   - the SHA-256 of every reviewed CTML file, every packed input, every
     reference file and every output;
3. packs it with the four tables, `manifest.json` and the inputs into
   `releases/<tag>.tar.gz`, byte for byte reproducible, plus a `.sha256`
   file;
4. creates an annotated git tag at HEAD. Its message records the archive's
   SHA-256, every output's, and the note.

`verify` checks an archive against its `.sha256` file, `release.json` and the
tag, packed inputs included. The tag is the one record not stored beside the
archive, so rewriting all three together still fails. `--rebuild` builds
again from the tagged commit in a temporary worktree, with the packed inputs
restored, and requires byte-identical outputs.

Nothing leaves the machine until you publish: `create` tags locally and
prints the commands to push the tag and upload the archive (a GitHub
Release, or Kispi storage). `releases/` is gitignored.

For the consuming pipeline: read the tables from an extracted release, never
from `index/`; check the archive with its `.sha256`; and write the tag (for
example `index-2026.10.01`) into every report that uses a match. "Why did
this sample match that trial?" is then answered by that release's CTML at
that commit.
