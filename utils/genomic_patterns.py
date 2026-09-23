import re

# Keywords indicating mutation details (variant_classification, exon) may be present
MUTATION_DETAIL_KEYWORDS = [
    # Exon-related (full form)
    r'\bexon\s*\d+',  # "exon 14", "exon14", "Exon 20"
    r'\bexon\b',
    # Exon shorthand notation (e.g., "ex20ins", "ex19del", "EGFR ex20ins")
    r'\bex\d+ins\b',  # "ex20ins"
    r'\bex\d+del\b',  # "ex19del"
    # Deletion types
    r'\bdeletion\b',
    r'\bin[- ]?frame\s+del',
    r'\bframeshift\b',
    r'\bframe[- ]?shift\b',
    # Insertion types
    r'\binsertion\b',
    r'\bin[- ]?frame\s+ins',
    # Splice variants
    r'\bsplice\b',
    r'\bsplicing\b',
    r'\bskipping\b',  # "exon14 skipping", "Exon 14 skipping"
    # Truncating mutations
    r'\btruncating\b',
    r'\btruncation\b',
    r'\bnonsense\b',
    # Missense
    r'\bmissense\b',
    # Other mutation types
    r'\bindel\b',
    r'\bpoint\s+mutation\b',
]

# Keywords indicating CNV details (cnv_call) may be present
CNV_DETAIL_KEYWORDS = [
    # Amplification
    r'\bamplification\b',
    r'\bamplified\b',
    r'\bhigh\s+amplification\b',
    r'\blow\s+amplification\b',
    # Homozygous/Heterozygous deletion patterns (various word orders)
    r'\bhomozygous\s+deletion\b',  # "homozygous deletion"
    r'\bheterozygous\s+deletion\b',
    # Allow an intervening gene or descriptor between "homozygous"/"heterozygous" and "deletion",
    # e.g. "homozygous methylthioadenosine phosphorylase (MTAP) deletion"
    r'\bhomozygous\b(?:\W+\w+){0,5}?\W+deletion\b',
    r'\bheterozygous\b(?:\W+\w+){0,5}?\W+deletion\b',
    r'\bhomozygous\s+\w+[- ]?deletion\b',  # "Homozygous MTAP-deletion"
    r'\b\w+[- ]?deleted\b',  # "MTAP-deleted", "MTAP deleted"
    # Loss patterns
    r'\bhomozygous\s+loss\b',
    r'\bheterozygous\s+loss\b',
    r'\bgene\s+loss\b',
    # Generic "GENE loss" pattern, e.g. "MTAP loss"
    r'\b\w+\s+loss\b',
    r'\bloss\s+of\s+\w+\s+expression\b',  # "loss of MTAP expression"
    # Deficiency patterns
    r'\bdeficient\b',  # "MTAP deficient"
    r'\bdeficiency\b',
    # Gain
    r'\bgain\b',
    r'\bcopy\s+number\s+gain\b',
    r'\bcopy\s+gain\b',
    # Copy number specific
    r'\bcopy\s+number\s+loss\b',
    r'\bhigh\s+copy\b',
    r'\blow\s+copy\b',
]

# Protein changes are no longer checked by pattern here: see
# utils/protein_change.py, which checks them against the reference protein.

