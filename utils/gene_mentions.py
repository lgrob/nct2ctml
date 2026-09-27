"""
Gene names written in trial text in forms a whitespace-token lookup misses:
a gene glued to a protein change, and histone H3 variants written without a
gene symbol. Deterministic, no model involved.

Shared by the gene scan (src/trial_criteria_to_genes), the mapper's text
checks (src/match_criteria_mapper._flag_unsupported_genes and
_text_mentions_gene) and the review sheet (utils/review_helper), so the three
agree on what counts as the text naming a gene.

1. Glued gene + change. NCT07306299 writes "H3.3K27M, H3.1K27M, H3.3G34R ...
   or EGFRvIII": no token is a gene, so H3-3A, H3C2 and EGFR were flagged
   gene_unsupported although the text names them. A token is split only when
   its tail is a protein change - one-letter residue, position, residue or
   "*"/"X", optionally after "p." (V600E, p.K27M, R132H, Q61*) - or, for EGFR
   only, the variant forms vII/vIII/vIV. The residues are upper case and the
   change must end the token, so "CD19CAR", "IL2RA", "H3K27a" and "H3K27me3"
   never split. The head must still resolve as a gene through the caller's
   own rules (the synonym table and its short-alias rule in the scan).

2. Histone H3 variants without a gene: "H3K27M", "H3 K27M", "H3K28M",
   "H3G34R/V", "H3 G34-mutant". They name a MUTATION of histone H3, so a
   mutation criterion on an H3 gene is supported. K27/K28 (legacy/HGVS
   numbering) count for the H3.3 and H3.1 genes where K27M occurs; G34/G35
   only for the H3.3 genes. Only a stated mutation counts: a residue letter
   after the position, or the words mutant/mutation/mutated, or a
   parenthesised residue list "(R/V)". "H3 K27-altered", "DMG-H3K27a",
   "H3K27me3 loss" and "loss of H3K28 trimethylation" do not: H3 K27-altered
   is a diagnosis that includes tumours with no H3 mutation (EZHIP
   overexpression, K27me3 loss), and EZHIP is never read as an H3 gene.
"""
import re

# One-letter amino acids. B, J, O, U, X and Z are left out of the reference
# residue, so a token like "CD3E" or "B7H3" is not a residue + position.
_AA = "ACDEFGHIKLMNPQRSTVWY"
PROTEIN_CHANGE = rf"(?:p\.)?[{_AA}]\d{{1,4}}(?:[{_AA}]|\*|X)"
EGFR_VARIANT = r"[vV](?:II|III|IV)"

# A token that is a gene head and a change tail, nothing else. The head is
# matched lazily, so "IDH1R132H" gives IDH1, "PIK3CAH1047R" gives PIK3CA.
_GLUED = re.compile(rf"^(?P<head>.+?)(?:(?P<change>{PROTEIN_CHANGE})|(?P<egfr>{EGFR_VARIANT}))$")

# The same tails as a right boundary after a name found in running text:
# "BRAF" in "BRAFV600E". Case-sensitive even inside an IGNORECASE pattern.
GLUED_TAIL = rf"(?=(?-i:{PROTEIN_CHANGE})(?![A-Za-z0-9]))"
EGFR_TAIL = rf"(?=(?-i:{EGFR_VARIANT})(?![A-Za-z0-9]))"

H3_K27_GENES = ("H3-3A", "H3-3B", "H3C2", "H3C3")   # H3.3 and H3.1
H3_G34_GENES = ("H3-3A", "H3-3B")                   # H3.3 only

_H3_VARIANT = re.compile(
    r"(?<![A-Za-z0-9.])H3[\s\-]?(?:p\.)?(?P<site>K2[78]|G3[45])"
    rf"(?:[{_AA}](?:/[{_AA}])*(?![A-Za-z0-9])"                      # K27M, G34R/V
    r"|[\s\-]?(?:(?i:mutant|mutation|mutated)"                     # G34-mutant
    rf"|\(\s*[{_AA}](?:\s*/\s*[{_AA}])*\s*\)))")                    # G34 (R/V)


def split_glued(token):
    """
    The gene head of a token that is a gene glued to a protein change, or None.

    "BRAFV600E" -> "BRAF", "H3.3K27M" -> "H3.3", "EGFRvIII" -> "EGFR".
    Purely syntactic: "CDKN2A" gives "CDK". The caller decides whether the
    head is a gene and must not split a token that is itself a gene name.
    A vII/vIII/vIV tail is accepted only after EGFR.
    """
    m = _GLUED.match(token or "")
    if not m:
        return None
    head = m.group("head")
    if m.group("egfr") and head.upper() != "EGFR":
        return None
    return head


def right_boundary(gene=None):
    """Regex for the end of a name: not followed by a letter or digit, unless a glued change follows."""
    tails = [GLUED_TAIL] + ([EGFR_TAIL] if (gene or "").upper() == "EGFR" else [])
    return r"(?:(?![A-Za-z0-9])|" + "|".join(tails) + ")"


def name_pattern(name, gene=None):
    """Whole-word `name`, or `name` glued to a protein change (see right_boundary)."""
    return r"(?<![A-Za-z0-9])" + re.escape(name) + right_boundary(gene or name)


def histone_variants(text):
    """[(start, end, genes)] for every H3 mutation written without a gene symbol."""
    out = []
    for m in _H3_VARIANT.finditer(text or ""):
        genes = H3_K27_GENES if m.group("site").startswith("K") else H3_G34_GENES
        out.append((m.start(), m.end(), genes))
    return out


def histone_variant_genes(text):
    """The H3 genes named by histone variant forms in text (see histone_variants)."""
    return sorted({g for _, _, genes in histone_variants(text) for g in genes})
