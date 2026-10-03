# Three small fixes from the audits: contradictions, floor guards, registry ages (2026-10-03)

- **Date:** 2026-10-03
- **Roadmap:** 3.4 follow-up
- **Outcome:** adopted, by the user's instruction ("do 1-3"); always on

**Question.** The [second audit](../runs/2026-10-02-3.4-audit-2.md) and the
[gene audit](../runs/2026-10-02-3.4-gene-audit.md) left three cheap fixes.
Each is deterministic, so each can be measured by replay:
1. **Trials that match nobody:** they require an alteration and exclude
   its own gene.
   - Ph+ CML as BCR SV with ABL1 !SV (2025-522138-29-00).
   - A step-level ROS1 exclusion against every arm's ROS1 (NCT05118789).
2. **Four text-floor false positives:**
   - "acute leukemia" inside a classification name (NCT06130579);
   - "acute leukemia" in "T-cell acute leukemia/lymphoma" (NCT06742463);
   - neuroblastoma in "CNS neuroblastoma" (NCT07087002);
   - the Hodgkin parent from "classical Hodgkin lymphoma" (NCT06563245).
3. **Registry age fields that contradict the text:** an adult myeloma trial
   with maximumAge "18 Years" (NCT07529782).

**Method.**
1. **Contradictions:** `match_criteria_mapper.find_unsatisfiable_genes` now
   also sees two cases. A hit is written as `genomic_contradiction`, which
   routes to review as before.
   - **The partner a required SV implies.** This is a short curated list
     (BCR→ABL1, PML→RARA, RUNX1T1→RUNX1, CBFB↔MYH11, AFF1→KMT2A,
     PBX1/HLF→TCF3), not the fusion table: ABL1 has many partners, and
     "ABL-class Ph-like, not BCR::ABL1" is a real eligibility pattern.
   - **A step's criteria with each arm's.** MatchMiner combines them with
     AND.
2. **Floor guards:** row guards in `ref/diagnosis_groups.tsv`:
   - a T/B-cell or T/B-lineage prefix before "acute leukemia";
   - "classical" or "nodular lymphocyte-predominant" before "Hodgkin
     lymphoma";
   - "CNS" before "neuroblastoma".

   And one in the loader's global guard: a term inside "classification of
   ...".
3. **Registry ages:** `age_bounds.registry_conflict` compares the registry
   bounds with the model's reading of the age sentence. A conflict is
   written as `age_registry_conflict`, which routes to review; the published
   bounds stay the registry's.
   - **The first version** reported any disagreement over a year: 40 trials,
     32 of them published.
   - **Half of those** were a registry wider than the text (minimumAge 14
     against "18 or older"). That only over-matches and often means the
     text quoted one cohort.
   - **The adopted version** reports only the direction that loses
     patients:
     - the registry stops where the text starts;
     - the registry minimum is more than a year above the text's;
     - the registry maximum (completed-units reading) is more than a year
       below the text's.

     A year of tolerance absorbs the inclusive/exclusive ambiguity of a
     maximum.

**Measured** by replay of all 1,133 trials, against the replay with the gene
rules ([2026-10-02-gene-rules.md](2026-10-02-gene-rules.md)): 33 trials
change; 15 published trials move to review, none the other way.

| fix | trials |
|---|---|
| contradictions found | 2, exactly the two audit cases; both were published |
| registry age conflicts | 18 (13 published; 5 already in review, 4 of them the days-for-years trials `age_units_implausible` already flags) |
| diagnoses removed by the floor guards | 14 trials, no additions |

- **The floor removals:**
  - **Hodgkin parent, 10 trials:** each still has Classical Hodgkin
    Lymphoma (or its subtypes) from the model.
  - **Neuroblastoma, 3 trials** (NCT07087002, 2024-518964-11-01,
    NCT06942039): the text means CNS neuroblastoma, a CNS embryonal tumour.
  - **Acute leukaemia, 2 trials:** the classification name (NCT06130579)
    and T-cell acute leukemia/lymphoma (NCT06742463).
- **The age conflicts** are mostly paediatric trials whose registry caps at
  17 or 18 while the text admits young adults to 21-30. Of the 13
  published:
  - 8 are a registry maximum below the text's;
  - 4 are a registry minimum above the text's;
  - 1 is NCT07529782, the audit case.

**Decision.** Adopted. Each fix only removes a floor term the text does not
support, or holds a trial back for a curator.

Not done: NCT06664411 (minimumAge 14 against "18 or older" in the text)
stays published as an over-match. That is deliberate: it is the wider
direction.
