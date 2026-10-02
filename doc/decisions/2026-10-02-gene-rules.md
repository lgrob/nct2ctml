# Gene criteria: three encoding rules and a scope check (2026-10-02)

- **Date:** 2026-10-02
- **Roadmap:** 3.4 follow-up
- **Outcome:** adopted, by the user's instruction ("do 3 and 4" after the
  [gene audit](../runs/2026-10-02-3.4-gene-audit.md)). Always on; there is no
  setting.

**Question.** The gene audit found 30 of 80 trials with gene criteria losing
eligible patients through them. Two groups looked fixable without a model:
- **Encodings that are wrong whatever the trial means (item 3):**
  - a required ITD written as a structural variant;
  - a "V600E" exclusion written for every BRAF mutation;
  - a medulloblastoma subgroup written as a gene.
- **A gene required of everyone where the text gives it for one cohort, or
  as one route beside others (item 4):** 10 losses, the largest group. The
  existing role check already runs on these genes and missed all 10, so
  these trials are routed to review, not rewritten.

**Method.**
- **Item 3:** `text_rules.fix_gene_encodings`, applied in `TrialMapManager`
  after mapping (both registries) and recorded as `gene_encoding_fixed`
  (information, does not route).
  - **ITD:** a required gene written as Structural Variation, where the text
    says "<gene>-ITD", "internal tandem duplication" (or a bare "ITD" for
    FLT3), keeps the structural variant and gets a Mutation alternative.
    - An ITD is an in-frame insertion, which callers and MatchMiner's records
      file as a mutation.
    - Not applied where the text calls the gene a fusion or rearrangement,
      or where the criterion has a fusion partner.
    - Exclusions are left alone (see below).
  - **One protein change:** an exclusion on a whole gene (`!Mutation`,
    `!Any Variation`) gets the protein change when every mention of the gene
    in the eligibility text carries the same verified change ("without a
    BRAFV600E mutation" → `!Mutation p.V600E`; "BRAF V600" → `p.V600`).
    - Drug classes ("prior BRAF inhibitor") are not counted as mentions.
    - A plain "BRAF mutation" anywhere leaves the exclusion as it is.
  - **Subgroup names:** SHH criteria are removed when every "SHH" in the
    text names the medulloblastoma subgroup ("SHH-activated", "SHH
    subtype", "SHH-TP53", ...); SHH-MB is driven by PTCH1/SUFU/SMO.
    - If that removes the trial's last required gene, the trial gets
      `genomic_emptied` and goes to review.
- **Item 4:** `text_rules.gene_scope_suspect`, written as
  `gene_scope_suspect` (routes to review).
  - **Which genes:** genes required at step level only, not in an arm's own
    criteria.
  - **When a mention of the gene counts as scoped:**
    - the gene is named both positive and negative (a stratifier);
    - its sentence limits it to a cohort;
    - it sits under a "... only" header;
    - it sits under a phase/cohort/arm header while a sibling section names
      a population and no required gene;
    - its criterion opens alternatives ("one of the following", "either",
      "OR") and one alternative names a population or disease state (MRD,
      relapse) and no gene;
    - a stand-alone OR joins it to a criterion without a gene;
    - labelled alternatives ("ETP-ALL: ... T-ALL with myeloid mutations:
      ...") include one without a gene.
  - **Tuning:** on the audit's 80 trials, then checked on the 13 flags
    outside the audit.
- **Measured by replay** of the gpt-oss corpus: both runs' saved answers,
  1,133 trials, against the same replay without the rules (the pipeline of
  the second audit).

**Result.**

| | |
|---|---|
| trials whose CTML changes | 40, all from these rules |
| published → review | 26 (24 scope, 2 SHH-only trials emptied) |
| review → published | 0 |
| ITD alternative added | 11 trials (7 published, 1 of them also scope-flagged; 3 already in review), FLT3 9, BCOR 1, UBTF 1 |
| exclusion narrowed to one change | 2 (NCT04166409 p.V600E, NCT05099003 p.V600) |
| SHH removed | 3 (2 required → review, 1 exclusion) |

- **Effect on the gene audit's 30 losses:**
  - **10 now go to review** for scope:
    - 9 of the 10 scope losses (all but NCT04469764, whose two cohorts are
      parallel bullets the cues do not see);
    - 2023-510063-35-00, a missing alternative, caught by its "either".
  - **3 are corrected:**
    - NCT06262438, FLT3-ITD;
    - NCT04166409 and NCT05099003, BRAF V600.
  - **1 goes to review emptied:** 2024-517133-40-00 (COGNITO-MB, SHH).
  - **16 remain:**
    - 4 subgroup exclusions;
    - 4 IHC-only routes;
    - 4 incomplete gene lists;
    - 2 defining-alteration contradictions;
    - 1 pMMR exclusion;
    - NCT04469764.
- **False alarms:**
  - **In the audit:** 1 of 43 correct trials flagged, 2023-507702-13-00. On
    reading, its phase 1 says "A RET gene alteration is not required
    initially", which the audit had missed; it is now marked borderline in
    `ctml/audit_2026-10-02-genes.tsv`.
  - **Outside the audit:** of the 13 flags, about 10 are real and 3 are
    false:
    - NCT04655404, an NTRK-fusion HGG trial with a "Surgical Cohort ONLY"
      sentence;
    - NCT04248569, where FLC carries the fusion by definition;
    - NCT04094610, ROS1/NTRK cohorts.

**Decision.** Adopted. The encoding rules only ever widen a requirement or
narrow an exclusion, so they cannot lose a patient who matched before. The
scope check moves trials to review and changes nothing in them.

What the rules deliberately do not do:
- **Make an ITD exclusion bite.** In the first replay they did. That turned
  CHIP-AML22's FLT3-ITD exclusion, which applies to one randomisation only
  (2023-504999-25-00, a subgroup exclusion in the audit), from excluding
  nobody into excluding every FLT3-ITD patient. Exclusion genes get no role
  check, and a wrong exclusion that excludes nobody only over-matches, so
  ITD exclusions stay as the model wrote them (REVEAL-ND,
  2025-522279-27-00, keeps over-matching).
- **Rewrite a scoped gene.** Moving a gene into its arm, or into an OR with
  the other routes, needs the trial's structure; a curator does it.

Not done:
- **The other items from the audit:**
  - the role check for exclusion genes (4 losses);
  - IHC routes (4);
  - the defining-alteration contradiction (2);
  - "e.g." lists (2).
- **The review helper's maintenance pass** (`utils/review/maintenance.py`)
  does not re-apply these rules to CTML written before this change. The next
  corpus rebuild does.
