# Arms narrower than their step go to review (2026-10-03)

- **Date:** 2026-10-03
- **Roadmap:** 3.4 follow-up
- **Outcome:** adopted, by the user's instruction; always on, routes to
  review

**Question.** In the [third audit](../runs/2026-10-03-3.4-audit-3.md), 4
losing trials had a step that lists a diagnosis no arm admits. A patient
must satisfy the step's match and one arm's, so those patients cannot match
at all:
- Perfume (NCT06159478): the step lists the low-grade gliomas, but the arm
  allows only "Low-Grade Glioma, NOS" and pancreatic adenocarcinoma;
- the MIBG trial (NCT00107289): the only arm requires neuroblastoma;
- VITAS (NCT04796012): both arms require RMS;
- NCT06972641: the arms require AML-MR.

**Method.** `text_rules.arm_narrower_than_step` compares, per step, the
patient codes the step's diagnoses reach with those the open arms reach
together. It uses `build_trial_index.diagnosis_population`, so subtrees,
NOS leaves and `_SOLID_`/`_LIQUID_` count as MatchMiner counts them.
- **An arm that clears the step:** one with no diagnosis criterion, or no
  match at all (every CTIS registration arm). It admits everyone.
- **Suspended arms** admit nobody.
- **A step diagnosis with codes no arm reaches** is written to
  `arm_narrower_than_step`, which routes the trial to review.

**Measured** on the replayed corpus (both gpt-oss runs, with the
2026-10-03 floor):
- **44 trials flagged, 31 of them published.** They move to review.
- **Nothing else changes.**
- **All 4 audit cases are among them.**

In 10 flagged trials read outside the audit, the step and its arms always
disagree, but in two directions:
- **The arm is too narrow, and patients are lost (about half):**
  - a PHEO/PGL diagnostic trial whose only arm is pheochromocytoma
    (NCT00004847);
  - a CD20/CD22 CAR-T for "lymphoid malignancies" whose only arm is B-ALL
    (NCT04283006);
  - Hürthle-cell carcinoma missing from the differentiated-thyroid arms
    (NCT06195228).
- **The step is too broad and the arms are right (the other half):** the
  arm already stops the over-match.
  - floor-added HGG types on a DIPG trial whose arms require DMG
    (NCT06838676);
  - AML on a lymphoid-malignancy trial (NCT04329728).

**Decision.** Adopted as a review flag, not a rewrite: which side is wrong
needs the text. The review advice names both cases. The cost is about 15
trials that lose no one, held for a curator.
