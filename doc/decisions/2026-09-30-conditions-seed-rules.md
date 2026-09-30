# Deterministic rules for the diagnosis seed (2026-09-30)

**Question.** The 3.4 audit attributed five of its nine confirmed error causes to the
conditions seed and to the unqualified-ALL lineage mapping. Which of those can a
deterministic rule catch, at what precision?

**Method.** Four candidate rules, each measured over all 1,146 indexed trials from the
cached registry records and the published CTML. No model calls.

## Adopted

**1. A basket resting on the word "oncology".** `trial_data_helper.all_tumours` reads a
sole condition of "cancer", "oncology" or "advanced cancer" as every tumour, so the trial
is published with `_SOLID_` + `_LIQUID_`. Restricted to the specialty word: **2 trials,
both wrong.**

| trial | conditions | published | text says |
|---|---|---|---|
| NCT04217512 | `Oncology` | _SOLID_ + _LIQUID_ + Head and Neck Carcinoma, Other (879 codes) | "Patients with head and neck cancer" |
| NCT07633236 | `Oncology Patients Receiving Chemotherapy`, `Cachexia-Anorexia Syndrome` | _SOLID_ + _LIQUID_ + Ovarian Cancer, Other; Stomach Adenocarcinoma | a supportive-care trial; probably out of scope altogether |

**2. B-lineage published where the text names only T-lineage.** Oncotree has no
lineage-free ALL node, so `ref/diagnosis_synonyms.tsv` maps unqualified ALL to B-ALL; a
T-cell trial that registers "Acute Lymphoblastic Leukemia" gets a B-lineage criterion it
never asked for. **8 trials**, including the two the audit found (NCT07070219,
NCT07070323 — the latter now carries a curated T-ALL copy, so it does not re-flag).

Both are written as one flag, `diagnosis_seed_suspect`, which routes the trial to review.
Nothing is removed from the match tree: case 1 may be a genuine basket whose text happens
to name one tumour, and case 2 may be a trial that really does enrol both lineages.

**3. Blocked diagnosis abbreviations** (`ref/diagnosis_abbrev_exclusions.tsv`, mirroring
`ref/gene_rewrite_exclusions.tsv`). A four-letter condition is an abbreviation, and an
ambiguous one resolves to whichever expansion the alias table happens to hold. Two
measured collisions are blocked at the source, so the seed produces nothing from them:

| abbreviation | wrongly resolved to | trial |
|---|---|---|
| `GCT` | Granular Cell Tumor | NCT07188441, a central malignant germ cell tumour study |
| `RAS` | Radiation-Associated Sarcoma | NCT07257653, colorectal, listing RAS beside BRAF |

A curator extends the file; the header says what belongs in it.

## Measured and not adopted

**4a. The same basket rule on "cancer".** 17 trials have a basket resting on a bare broad
word; 10 of them also name a specific diagnosis, and reading those as errors would be
wrong — they are the category headers the basket rule's own docstring is about
(NCT02813135's "Pediatric Cancer", NCT06033183's four named tumours). Restricting to
"oncology" is what makes the rule precise.

**4b. Automatic detection of abbreviation collisions.** Two discriminators were tried on
the 40 abbreviation-seeded rows. *Text corroboration* (the resolved name's words appear
in the text) flags 18, but almost all are correct expansions the text writes only as the
abbreviation — DIPG, BPDCN, ALCL, AITL, MDS, CML. *Lineage consistency* (the resolved
name shares no Oncotree ancestor with another resolved condition) flags 1, and that one
is a false positive (MPNST beside Wilms' Tumor). Oncotree's upper levels connect almost
everything, so lineage sharing cannot separate a collision from a co-enrolled diagnosis.
Hence the explicit list above.

**4c. Widening the unqualified-ALL rule so it adds T-ALL more often.** 141 trials carry
B-lineage without T-lineage where `all_lineage_unspecified` declines to fire. Every
sampled case is declining correctly: the text does name B-lineage ("B-ALL", "BCP",
"B precursor", "CD19"). Scoping the B-lineage evidence to lines that also mention ALL
reduces the set to 9, but those include curated trials that are right as they stand
(NCT03643276, an answer-key trial) and lineage statements that simply do not put "ALL" on
the same line. **Not adopted**: the existing suppression is doing its job, and the
recall direction of the ALL problem stays open.

## Effect

`review_helper flag-diagnosis-seed` flags **10 trials, all currently published**; the
list is `diagnosis_seed_flags_2026-09-30.tsv`. Not applied: moving published trials into
review waits for the user's go-ahead. The abbreviation block is at the source, so it
changes the next map run; existing CTML for NCT07188441 and NCT07257653 still carries the
wrong diagnosis until those two are re-mapped or corrected by hand.

One correction to the audit note: NCT07262489's Hepatocellular Carcinoma does **not**
come from the conditions seed. Its conditions are `['Localized Cancer']`, which resolves
to nothing, so the diagnosis came from the model reading an incidental HCC mention in a
bilirubin threshold. That case belongs to 2.7 (quote grounding), not here — so the seed
rules reach 2 of the audit's diagnosis-scope causes, not 3.
