# Diagnosis text floor: populations named in the inclusion text (2026-10-02)

- **Date:** 2026-10-02
- **Roadmap:** 3.4 follow-up
- **Outcome:** adopted: `DIAGNOSIS_TEXT_FLOOR = True`, as measured, by the
  user's decision

**Question.** The largest cause in the
[2026-10-02 audit](../runs/2026-10-02-3.4-audit.md) was named diagnoses missing
from the published list: 11 of 60 sampled trials lost eligible patients that
way. Stage 1 of the diagnosis mapping (organ branches) was right in all 11; the
loss was in stage 2. The model there:
- answers a group word with one example ("soft tissue or bone sarcoma" ->
  Liposarcoma);
- skips pre-2021 WHO names that have no OncoTree node of that name
  (anaplastic astrocytoma, oligodendroglioma, DIPG);
- does not turn "any solid tumour" in the text into a basket.

Can a curated table of how texts name a population, added to the model's
answer as a floor, recover these without costing too much precision?

**Method.**
- **The table.** `ref/diagnosis_groups.tsv`: 110 terms (glioma groups and
  old WHO names, sarcoma groups, leukaemia and lymphoma groups, baskets),
  drafted by Claude and revised by the user, who set every medical mapping
  choice.
- **Matching** (`reference_validation.diagnoses_from_text`):
  - whole words, longest term wins;
  - row guards, so a lineage prefix blocks "ALL" and a subtype blocks
    "rhabdomyosarcoma";
  - a global guard against assessment criteria (RECIST, RANO) and stated
    expertise ("pathologists with expertise in bone sarcomas");
  - two-sided row guards (the table's TODO 2, added after the first
    measurement): a guard containing "§" sees 80 characters on each side of
    the term, so a cue after it blocks too ("Blood Cancer United", "solid
    tumors of the following types", "acute lymphoblastic leukemia (B-ALL)",
    "NHL of B-cell origin", "LGG WHO grade I");
  - an abbreviation in brackets inherits its term's result;
  - a lineage veto: an unqualified ALL/LBL/NHL keeps only the lineage the
    text names, if it names exactly one.
- **Text read:** the inclusion criteria only. This record said "the title, the conditions and the inclusion criteria"; in fact neither registry passed the title, and ClinicalTrials.gov did not pass the conditions (corrected 2026-10-03; since then all three are read, see [2026-10-03-floor-groups-and-title.md](2026-10-03-floor-groups-and-title.md)).
- **Applied** in `seed_and_map_diagnosis` after the model call, so the
  prompts are unchanged.
- **Measured by replay**, not a new model run: both gpt-oss corpus runs
  (`20261001T125000Z-0bd723`, `20261001T192539Z-34b83e`, 11,118 saved
  answers), all 1,137 trials, floor off against floor on.
  - The floor-off replay reproduces the cluster output for 1,125 trials. In
    the other 12 the model was asked the same question twice within a trial
    and answered differently; replay returns the first answer, the same way
    in both arms.
- **Scoring:** the 56 benchmark trials against `ctml/reviewed`, and the 60
  audit trials against the audit verdicts.
- **Iterations:** four rounds of guard fixes after reading every benchmark
  match in context, then TODO 2. Numbers below are for the final version;
  the version before TODO 2 had NCT precision 0.654 and CTIS 0.921.

**Result.**

| | floor off | floor on |
|---|---|---|
| NCT population recall (50) | 0.938 | 0.938 |
| NCT population precision | 0.810 | 0.681 |
| NCT name F1 | 0.802 | 0.723 |
| NCT trials exactly right by population | 33 | 24 |
| CTIS population recall (6) | 0.889 | 0.889 |
| CTIS population precision | 1.000 | 1.000 |
| corpus trials whose diagnoses change | | 398 of 1,137 |
| corpus trials that lose a term | | 0 |
| routing changes | | 10 to review, 7 to mapped |

- **Audit trials:** the floor closes 9 of the 11 missing-diagnosis
  failures:
  - 2024-511350-41-00, NCT05956821, NCT03911388 and NCT06381570 get the
    glioma groups and current WHO names;
  - NCT06474676 and NCT07725380 get the sarcoma groups;
  - NCT07197554 gets `_SOLID_`, 2023-506581-31-00 the other acute
    leukaemias, NCT07584499 DIPG.

  Not closed: NCT06850285 (CD30+ lymphomas: a marker, not a diagnosis) and
  NCT04925609 ("other solid tumors" not matched).
- **The other unqualified-ALL failure stays:** 2025-522052-13-00 (FORUM2)
  is not fixed, because a sub-study mentions CD19 and the lineage veto then
  keeps B-ALL only.
- **The benchmark shows no recall gain.** Its curated trials mostly name
  their entities, so the floor's target failures are rare there.
- **The precision cost on the benchmark** (NCT -0.129):
  - **Nearly all of it is where the floor is wider than the curated key but
    the text supports it.** Examples:
    - "locally advanced and/or metastatic solid tumors may be enrolled in the
      dose escalation" -> `_SOLID_` (NCT06083883);
    - "B7-H3+ solid tumor" (NCT04897321);
    - HGG including DIPG -> every HGG code (NCT04655404);
    - "ependymoma, medulloblastoma, glioblastoma, or another type of primary
      cancer of the CNS" (NCT05106296);
    - "LGG WHO Grade I or II" -> the grade 1-2 entities (NCT07110246; listed
      as a false positive in the version before, wrongly);
    - neuroblastoma -> + ganglioneuroblastoma (NCT01704716, NCT04221035; the
      row alone costs 0.02);
    - MPAL named in the text and missing from the key (NCT07012447,
      NCT03643276).
  - **The genuine false positives found before TODO 2 are gone:** "Blood
    Cancer United territory", "pathologists with expertise in bone sarcomas",
    and "RMS types" / the ICR name firing the RMS parent.
  - **-0.02 unclear:** NCT05918640 ("recurrent or relapsed solid tumor
    failing primary therapy", key Ewing only).
- **Corpus:** the most frequent additions are ganglioneuroblastoma (93
  trials), Ewing sarcoma of soft tissue (62), the extracranial rhabdoid
  tumours and the other added STS members (45-49), `_SOLID_` (48), acute
  leukaemias of ambiguous lineage (48) and T-ALL (46).
- **Audit trials judged correct that change:** 5. Four get
  ganglioneuroblastoma; NCT06508931 gets Mature B-Cell Neoplasms and B-ALL
  from its "Burkitt leukemia" and B-NHL wording. Mature B-Cell Neoplasms
  also holds CLL/SLL and plasma cell neoplasms, the over-match the table's
  lymphoma note anticipates.

**Decision.** Adopted as is, by the user, on 2026-10-02. The floor buys back
missing-diagnosis recall on exactly the trials the audit found; the benchmark
cannot show that, by construction. It costs about 0.13 of benchmark NCT
precision and none on CTIS, and what it costs is the floor being wider than
the curated keys in ways the text supports; no false positive is left among
the benchmark trials.
- `config.DIAGNOSIS_TEXT_FLOOR` defaults to True in the same commit as this
  record.
- Every mapped file records `diagnosis_text_floor` in its `_provenance`, and
  the index shows it in `prompt_settings`.
- The corpus is rebuilt by replay of the saved gpt-oss answers
  ([../runs/2026-10-02-3.2-gpt-oss-full-run.md](../runs/2026-10-02-3.2-gpt-oss-full-run.md)).

Not done:
- **Rows the user may still narrow:** ganglioneuroblastoma, the Mature B/T
  lymphoma parents (they also hold CLL/SLL and plasma cell neoplasms), the
  medulloblastoma variants.
- **The curated keys** could be widened where the text supports the floor.
- **The table's loader TODOs 1 and 3-6.**
