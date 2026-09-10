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
#   'H3'  in  14 trials -> FGFR1 (H3  = histone H3; FGFR1 once carried H2-H5)
#   'CAP' in   2 trials -> BRD4  (CAP = a chemotherapy regimen / capecitabine)
# A spurious candidate gene is then offered to the LLM, which invites exactly
# the hallucination it is meant to avoid.
#
# Synonyms that must never resolve to a gene symbol.
blocked_gene_synonyms = ['ALL', 'CAP', 'H3', 'H4', 'H5']

# Synonyms that resolve only when the criteria text also contains one of the
# context keywords (case-insensitive). This recovers the true meaning of the
# blocked histone aliases above: in an H3 K27M trial, 'H3' should map to the
# histone H3 genes, never to FGFR1.
contextual_gene_synonyms = {
    'H3': (['k27', 'k27m', 'g34', 'histone'], ['H3F3A', 'H3F3B', 'HIST1H3B']),
    'H4': (['histone'], ['HIST1H4I']),
}
