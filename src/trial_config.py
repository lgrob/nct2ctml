# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

intervention_types = ["DRUG", "BIOLOGICAL", "COMBINATION_PRODUCT"]
# Countries whose recruiting sites make a trial eligible.
# An empty list means worldwide (no location filter).
regions = []
conditions = [
    # general oncology terms (kept from upstream)
    "cancer",
    "tumor",
    "tumour",
    "carcinoma",
    # paediatric-specific framing
    "pediatric cancer",
    "paediatric cancer",
    "childhood cancer",
    # entities that dominate paediatric oncology
    "leukemia",
    "lymphoma",
    "neuroblastoma",
    "sarcoma",
    "rhabdomyosarcoma",
    "osteosarcoma",
    "Ewing sarcoma",
    "medulloblastoma",
    "glioma",
    "retinoblastoma",
    "Wilms tumor",
    "hepatoblastoma",
    "germ cell tumor",
]

# ClinicalTrials.gov StdAge values used to restrict the search.
# CHILD = birth-17, ADULT = 18-64, OLDER_ADULT = 65+.
# Trials are tagged with every age band they enrol, so ['CHILD'] keeps
# paediatric-only trials AND mixed child/adult trials, and drops adult-only ones.
# Set to [] to disable the age filter entirely.
std_ages = ["CHILD"]

# Labels written to the CTML `age` field, derived from the trial's stdAges bands.
# Confirm these against the vocabulary your MatchMiner instance expects.
AGE_LABEL_ALL = "All"
AGE_LABEL_CHILDREN = "Children"
AGE_LABEL_ADULTS = "Adults"


# --- CTIS (EU Clinical Trials Information System) -------------------------
# CTIS is the current EU/EEA register (it replaced EudraCT for new trials in
# January 2023). Note that Switzerland is NOT in the EU/EEA and therefore has
# no presence in CTIS at all - these are trials a Swiss patient would travel
# for, not trials recruiting in Switzerland.
#
# ageGroupCode 2 = paediatric (0-17 years); 3 = adults; 4 = elderly.
ctis_age_group_codes = [2]

# CTIS has no structured condition coding, so the search is a free-text OR
# across these terms, de-duplicated by CT number.
ctis_conditions = [
    "cancer",
    "tumour",
    "tumor",
    "carcinoma",
    "neoplasm",
    "leukaemia",
    "leukemia",
    "lymphoma",
    "sarcoma",
    "blastoma",
    "neuroblastoma",
    "glioma",
    "medulloblastoma",
    "rhabdomyosarcoma",
    "osteosarcoma",
    "retinoblastoma",
    "hepatoblastoma",
    "nephroblastoma",
]

# Member-state trial statuses that count as open. CTIS reports exactly four
# values at member-state level, verified against the live API:
#   'Authorised'     - approved; may or may not have started recruiting
#   'Ended'          - finished
#   'Halted'         - suspended
#   'Not authorised' - refused
# 'Authorised' does not by itself mean recruiting; the per-state
# hasRecruitmentStarted flag drives the `countries` column in ctis_status.csv,
# so an open trial with no countries listed is authorised but not yet recruiting.
ctis_open_statuses = ["Authorised"]


# --- Gene synonym disambiguation ----------------------------------------
# ref/synonym_to_gene_symbol.tsv is derived from NCBI alias data, where some
# genes carry short historical aliases that mean something entirely different
# in oncology text. Measured across 924 paediatric trials, these fired as:
#   'ALL' in 133 trials -> BCR   (ALL = acute lymphoblastic leukaemia)
#   'H3'  in  14 trials -> FGFR1 (H3  = histone H3)
#   'CAP' in   2 trials -> BRD4  (CAP = a chemotherapy regimen / capecitabine)
# A spurious candidate gene is then offered to the LLM, which invites exactly
# the hallucination it is meant to avoid.
#
# Rebuilding the table from live NCBI (utils/build_gene_synonyms.py) removed
# the FGFR1 mappings - current NCBI lists no histone alias on FGFR1 - but did
# not remove the need for this list. NCBI still genuinely records ALL on BCR,
# CAP on BRD4, H4 on CCDC6, H5 on SEPTIN5 and H3 on H3C14. Those are correct
# as history and wrong as an oncology lookup, so the block stays.
#
# Synonyms that must never resolve to a gene symbol.
#
# Added 2026-09-27 (the user's go-ahead after the queue audit): short NCBI
# aliases that the scan resolved to genes although, in every whole-word use
# across the 1,255 cached trials, they mean something else. Because the scan
# found them, the unsupported-gene check passed, and 35 published trials
# carried a genomic criterion that the text supports only through one of these
# words (e.g. "DNMT3B any variation" from "informed consent form (ICF)").
# Uses in the cache / trials, and what they mean:
#   CAR  -> PRKAR1A  444 / 177  chimeric antigen receptor (CAR T cells)
#   II   -> CD74     316 / 211  Roman numeral: phase II, grade II, Factor II
#   B    -> ELF2     297 / 150  list item "b." (the table's alias is lower-case b)
#   CSF  -> CSF2     254 / 118  cerebrospinal fluid; G-CSF/GM-CSF drug names
#   ICF  -> DNMT3B   164 /  85  informed consent form
#   NHL  -> RTEL1    135 /  54  non-Hodgkin lymphoma
#   PN   -> USB1      58 /   5  plexiform neurofibroma
#   JMML -> PTPN11    30 /  22  juvenile myelomonocytic leukaemia (a diagnosis)
#   SF   -> HGF       28 /  24  shortening fraction (echocardiography)
#   MCL  -> FH        22 /  12  mantle cell lymphoma
#   MI   -> MITF      18 /  18  myocardial infarction
#   FSH  -> BRD2      18 /  11  follicle-stimulating hormone
#   NAT  -> BRD2      17 /   8  nucleic acid (amplification) testing
#   B1   -> MS4A1     15 /   3  randomisation arm B1
#   IP   -> SDHB      12 /   6  investigational product
blocked_gene_synonyms = [
    "ALL",
    "CAP",
    "H3",
    "H4",
    "H5",
    "CAR",
    "II",
    "B",
    "CSF",
    "ICF",
    "NHL",
    "PN",
    "JMML",
    "SF",
    "MCL",
    "MI",
    "FSH",
    "NAT",
    "B1",
    "IP",
    # trial-arm labels, not genes: 'ARM1' -> ADRM1 (NCT06972641), 'ARMD2' -> ABCA4
    "ARM1",
    "ARMD2",
]

# Synonyms that resolve only when the criteria text also contains one of the
# context keywords (case-insensitive). This recovers the true meaning of the
# blocked histone aliases above: in an H3 K27M trial, 'H3' should map to the
# histone H3 genes, not to H3C14 (which is histone H3.2).
#
# Symbols here must be current HGNC names, matching ref/genes.txt - the
# pre-2019 forms (H3F3A, HIST1H3B, HIST1H4I) live in the synonym table, which
# maps them onto these.
contextual_gene_synonyms = {
    # H3C3 (H3.1, HIST1H3C) carries K27M as H3C2 does; it was missing until
    # 2026-09-27, so 9 published K27M trials lacked it (gene_mentions.H3_K27_GENES).
    "H3": (["k27", "k27m", "g34", "histone"], ["H3-3A", "H3-3B", "H3C2", "H3C3"]),
    "H4": (["histone"], ["H4C9"]),
}


# Genes whose eligibility criteria are about protein expression, not a somatic
# alteration, so they must never become a `genomic` block in CTML.
#
# MatchMiner's genomic path matches a patient's sequencing report: mutations,
# copy number, structural variants. An antigen is measured by flow cytometry or
# IHC and lives on a different axis entirely - PD-L1 already has its own
# biomarker field for exactly this reason.
#
# The cost of getting this wrong is asymmetric and severe. A CAR-T trial
# enrolling "CD19+ and CD22+ acute lymphoblastic leukaemia" is describing the
# disease it treats; emitting that as a required CD19 mutation produces a trial
# that matches no patient at all, and nobody can see a trial that is missing.
# Paediatric oncology runs a lot of CAR-T and TCR trials, so this is not rare:
# it fired on NCT02443831 (CD19/CD22) and NCT06083883 (NY-ESO-1, HLA-A) in one
# 50-trial benchmark.
#
# Deliberately narrow. A gene belongs here only when it is used as an
# immunophenotype or HLA restriction and essentially never as a somatic
# criterion. CD74 is NOT here despite showing up as a false positive - it forms
# real fusions (CD74-ROS1, CD74-NRG1) that a trial can legitimately require.
expression_only_genes = [
    "CD19",  # CAR-T target, flow cytometry
    "CD22",  # CAR-T target, flow cytometry
    "CD274",  # PD-L1; has its own pdl1_status field
    "CD276",  # B7-H3; CAR-T/ADC target by IHC - all 11 cached mentions are expression
    "MS4A1",  # CD20; antibody/CAR target by flow or IHC - all 62 cached mentions (41 trials) are expression
    "CTAG1B",  # NY-ESO-1; cancer-testis antigen for TCR therapy, IHC
    "HLA-A",  # TCR restriction, HLA typing rather than tumour sequencing
    "HLA-B",
    "HLA-C",
]
