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
