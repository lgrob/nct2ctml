# Text floor: eight more groups, and it now reads the title and conditions (2026-10-03)

- **Date:** 2026-10-03
- **Roadmap:** 3.4 follow-up
- **Outcome:** adopted, by the user's instruction (the group rows from the
  [third audit](../runs/2026-10-03-3.4-audit-3.md)); the floor stays on

**Question.** 24 of the third audit's 34 losing trials had a named
population missing. Several looked like rows the
[text floor](2026-10-02-diagnosis-text-floor.md) lacked:
- pheochromocytoma/paraganglioma;
- germ-cell tumours;
- B-cell malignancies;
- acute leukaemias;
- non-uveal melanoma;
- myelofibrosis;
- head and neck carcinoma;
- "solid and blood cancers".

**What was found first.** Two of those already had rows ("acute leukemia",
"blood cancer"), and the floor still missed them.
- **The floor read neither the title nor the conditions:**
  - in labelled mode the diagnosis input carries neither for
    ClinicalTrials.gov, and no title for CTIS;
  - so "High-Risk Acute Leukemias" in NCT07573111's title, and "solid
    tumours and blood cancer" in 2023-510424-68-00's, never reached it.
- **The floor's decision record was wrong:** it said the floor read the
  title, conditions and inclusion text. It read the inclusion text only.

**Method.**
- **`seed_and_map_diagnosis(..., title=...)`.** Both registries pass the
  title. The floor runs after the model, so prompts and replays are
  unchanged.
  - **Named populations:** one pass over title, conditions and inclusion
    text together, so the lineage veto sees the whole trial. That keeps
    "ALL" in a CD19 CAR-T title B-lineage.
  - **Union with the old pass:** the pass over the inclusion text alone is
    kept and the two are combined. A "B-cell" title must not let the veto
    drop a T-lineage the text admits (NCT04099966).
  - **Basket wildcards:** from the inclusion text, as before.
    - From the title only when nothing specific was found. An umbrella title
      ("... HEMatological Malignancies in Children, Subprotocol D",
      NCT05658640) heads a one-disease subprotocol.
    - Never from the conditions list. `_basket_wildcards` decides that, and
      treats "Pediatric Solid Tumor" ahead of a list as a header.
- **New rows in `ref/diagnosis_groups.tsv`** (section "2026-10-03"):
  - **PPGL:** both nodes, plus paraganglioma and the British phaeo-
    spellings.
  - **Germ-cell tumour:** testis (seminoma and non-seminoma), ovary and
    extragonadal.
    - CNS germ-cell tumours get their own row; paediatric protocols treat
      them separately.
    - Qualified forms (non-seminomatous, mixed, CNS, ovarian ...) are left to
      the model.
  - **B-cell malignancy / hematolymphatic / neoplasm:** B-ALL plus mature B.
    "mature B-cell malignancy" gives mature B only.
  - **Non-uveal melanoma:** skin melanoma, the five mucosal sites and
    conjunctival. **Mucosal melanoma:** the five mucosal sites.
  - **Myelofibrosis:** primary, post-PV and post-ET.
  - **Head and neck cancer/carcinoma:** the Head and Neck carcinomas
    (cancer also includes the mucosal melanoma).
  - **"solid and/or hematologic malignancies", "solid and liquid tumors":**
    both wildcards.
  - **Acute leukemia guard:** now also blocks "myeloid" and "lymphoblastic"
    before the term ("Myeloid Acute Leukemia", NCT05503134).
- **Measured** by replay of both gpt-oss runs (11,118 answers), against the
  replay of the current pipeline.

**Result.**

| | before | after |
|---|---|---|
| benchmark NCT population recall (50) | 0.94 | 0.96 |
| benchmark NCT population precision | 0.68 | 0.65 |
| corpus trials whose diagnoses change | | 142 of 1,132, additions only |
| routing | | 1 review → published (2024-513509-30-00: had no diagnosis, now germ-cell tumours); 1 published → review (NCT07492316: a new term is named in its exclusions) |

- **The audit's 24 missing-population losses:**
  - **Fixed, 9:**
    - 2023-510424-68-00 (`_LIQUID_`);
    - 2024-520054-38-00 (germ-cell tumours);
    - NCT04888741 (post-PV/ET myelofibrosis);
    - NCT06092047 (B-ALL);
    - NCT06462248 (mature B);
    - NCT06669013 (the STS list);
    - NCT06912763 (head and neck);
    - NCT07573111 (ALL);
    - NCT07680205 (paraganglioma).
  - **Partly fixed, 3:**
    - NCT04254419 gets the HGGs, but not medulloblastoma;
    - NCT06398444 gets paraganglioma, but not GEP-NET;
    - NCT06159478 gets the LGG nodes at step level, but its arm still
      restricts them.
  - **Not reached, 12:**
    - the RET and PRKACA baskets;
    - 2024-516914-39-00, where "non-uveal" is separated from "melanoma" by
      the stage wording;
    - and others the text names in ways no group row covers.
- **The precision cost on the benchmark (-0.03)** is the floor being wider
  than the curated keys where the text supports it:
  - ONC206 (NCT04732065), whose conditions list glioblastoma, ependymoma
    and grade III glioma;
  - the Ewing soft-tissue convention (NCT07297979).
- **The conditions-only baseline** (`bench/baseline_conditions_nct.json`) was
  updated, because the floor now reads the conditions too.

**Decision.** Adopted: in the code and table, always on with the floor.

Not done:
- **Arm narrower than its step:** NCT06159478, and 3 more trials in the
  audit. A separate check.
- **Rows for the 12 losses no group row reaches.**

## Addendum: three small rows (2026-10-03)

Added after the arm check, by the user's instruction:
- **`BALL`:** B-ALL without the hyphen, capitals only (2023-508357-58-00).
- **"aggressive (mature) B-cell lymphoma / B-NHL":** DLBCL, Burkitt and
  Burkitt-like, the HGBLs, PMBCL, the IRF4, ALK+, T-cell/histiocyte-rich and
  EBV+ large B-cell lymphomas (NCT05533775).
  - Guarded against history and AIDS-defining-cancer clauses ("No history of
    AIDS-defining cancers (e.g. ... aggressive B-cell lymphoma ...)",
    NCT04055220).
- **"solid tumor(s)/malignancy or/and lymphoma(s)":** `_SOLID_` plus the
  lymphoma groups (NCT04084067), with the solid tumor row's enumeration
  guard.

**Replay:**
- 20 trials gain terms, none lose one, and no routing changes.
- The benchmark is unchanged: NCT population recall 0.96, precision 0.65.
- The third audit's three trials are now covered: 2023-508357-58-00
  (B-ALL), NCT05533775 and NCT04084067.

