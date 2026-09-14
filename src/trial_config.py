# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

intervention_types = ['DRUG','BIOLOGICAL','COMBINATION_PRODUCT']
# Countries whose recruiting sites make a trial eligible.
# An empty list means worldwide (no location filter).
regions = []
conditions = [
    # general oncology terms (kept from upstream)
    'cancer', 'tumor', 'tumour', 'carcinoma',
    # paediatric-specific framing
    'pediatric cancer', 'paediatric cancer', 'childhood cancer',
    # entities that dominate paediatric oncology
    'leukemia', 'lymphoma', 'neuroblastoma', 'sarcoma',
    'rhabdomyosarcoma', 'osteosarcoma', 'Ewing sarcoma',
    'medulloblastoma', 'glioma', 'retinoblastoma',
    'Wilms tumor', 'hepatoblastoma', 'germ cell tumor',
]

# ClinicalTrials.gov StdAge values used to restrict the search.
# CHILD = birth-17, ADULT = 18-64, OLDER_ADULT = 65+.
# Trials are tagged with every age band they enrol, so ['CHILD'] keeps
# paediatric-only trials AND mixed child/adult trials, and drops adult-only ones.
# Set to [] to disable the age filter entirely.
std_ages = ['CHILD']

# Labels written to the CTML `age` field, derived from the trial's stdAges bands.
# Confirm these against the vocabulary your MatchMiner instance expects.
AGE_LABEL_ALL = 'All'
AGE_LABEL_CHILDREN = 'Children'
AGE_LABEL_ADULTS = 'Adults'


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
    'cancer', 'tumour', 'tumor', 'carcinoma', 'neoplasm',
    'leukaemia', 'leukemia', 'lymphoma', 'sarcoma', 'blastoma',
    'neuroblastoma', 'glioma', 'medulloblastoma', 'rhabdomyosarcoma',
    'osteosarcoma', 'retinoblastoma', 'hepatoblastoma', 'nephroblastoma',
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
ctis_open_statuses = ['Authorised']


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
blocked_gene_synonyms = ['ALL', 'CAP', 'H3', 'H4', 'H5']

# Synonyms that resolve only when the criteria text also contains one of the
# context keywords (case-insensitive). This recovers the true meaning of the
# blocked histone aliases above: in an H3 K27M trial, 'H3' should map to the
# histone H3 genes, not to H3C14 (which is histone H3.2).
#
# Symbols here must be current HGNC names, matching ref/genes.txt - the
# pre-2019 forms (H3F3A, HIST1H3B, HIST1H4I) live in the synonym table, which
# maps them onto these.
contextual_gene_synonyms = {
    'H3': (['k27', 'k27m', 'g34', 'histone'], ['H3-3A', 'H3-3B', 'H3C2']),
    'H4': (['histone'], ['H4C9']),
}
