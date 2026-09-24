"""
Trial protein changes in HGVS notation, checked against the reference
protein.

Trials write protein changes the way the literature does: one-letter codes,
often without "p.", sometimes in legacy numbering ("V600E", "p.G12C",
"H3 K27M", "E746_A750del", "G719X"). The pipeline's VEP annotation writes
HGVS against the MANE Select protein ("ENSP00000493543.1:p.Val600Glu"). A
join between the two needs one notation, and it has to be the official one.

`normalise(gene, stated)` rewrites a stated change as HGVS three-letter
protein notation on the gene's MANE Select protein. It then checks the
result deterministically against the sequence in
ref/mane_select_proteins.tsv: every residue the notation names must be the
residue the reference protein carries at that position. An insertion's two
flanking residues must also be adjacent, and a range must run forwards. A
change that fails is not emitted in HGVS form. It is returned with the
reason instead, because a notation that names the wrong residue describes a
different variant, and a join on it would silently match the wrong patients.

Histone H3 is the one deliberate renumbering. Histone literature counts
residues on the mature protein, which has lost its initiator methionine, so
the "K27M" of diffuse midline glioma is p.Lys28Met in HGVS, and "G34R" is
p.Gly35Arg. The rule applies to every gene whose MANE protein begins with
the histone H3 N-terminus, which is a property of the sequence rather than
a list of names, and the shifted position is checked like any other. It is
recorded in `numbering`, so the renumbering is visible, not silent. A change
already written in three-letter code is HGVS numbering and is not shifted.

A one-letter H3 change is read in legacy (mature) numbering first, as
before. Only when that reading does not match the reference and the HGVS
reading does is the change taken as already in HGVS numbering: trials
write "p.K28M, p.G35R" (NCT07110246), and mature K28 is serine, G35
valine. Legacy wins whenever it fits, because both readings fit where
residues repeat (G34 and G35 are both glycine, so "G34R" fits either) and
the literature form is then the meaning. If neither fits it is a
reference_mismatch on the legacy reading.

What is not handled is returned as "unparsed", never guessed: multi-residue
alternatives ("V600E/K"), exon-level descriptions ("exon 19 deletion"), and
anything else outside the grammar below.

    X99Y  X99*  X99Ter  X99=      substitution, nonsense, synonymous
    X99X  (trailing X)            any substitution at X99 (this repo's
                                  wildcard convention, see
                                  src/match_criteria_mapper.py)
    X99                           the residue itself (any change)
    X99del  X99_Y100del           deletion
    X99dup  X99_Y100dup           duplication
    X99_Y100insZZ                 insertion
    X99delinsZZ  X99_Y100delinsZZ deletion-insertion
    X99fs  X99Yfs*12  X99fsTer12  frameshift (written in the short form)

Each of these may be written with or without "p.", in one- or three-letter
code, and with or without HGVS's parentheses for predicted changes.
"""
import csv
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import config

REFERENCE = config.PROTEIN_REFERENCE_FILE_PATH

THREE = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln",
         "E": "Glu", "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys",
         "M": "Met", "F": "Phe", "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp",
         "Y": "Tyr", "V": "Val", "U": "Sec", "O": "Pyl"}
ONE = {v.upper(): k for k, v in THREE.items()}

# Mature histone H3 begins ARTKQTARKSTGGKAPRKQLA; the precursor adds Met.
_H3_N_TERMINUS = "MARTKQTARKSTGGKAPRKQLA"

VERIFIED = "verified"


@dataclass
class ProteinChange:
    stated: str
    gene: str
    status: str                       # "verified" or the reason it is not
    hgvs: str = ""                    # "p.Val600Glu"; empty unless verified
    kind: str = ""                    # substitution, deletion, any_change, ...
    refseq_protein: str = ""
    ensembl_protein: str = ""
    numbering: str = "hgvs"           # or "histone_mature" when shifted
    detail: str = ""

    @property
    def verified(self):
        return self.status == VERIFIED


@dataclass
class _Parsed:
    kind: str
    residues: list = field(default_factory=list)   # [(one-letter, position)]
    alt: str = ""                                   # one-letter string
    tail: str = ""                                  # frameshift remainder


@lru_cache(maxsize=4)
def load_reference(path=REFERENCE):
    """symbol -> (refseq, ensembl, sequence), read once."""
    reference = {}
    with open(path) as handle:
        rows = csv.DictReader((line for line in handle if not line.startswith("#")),
                              delimiter="\t")
        for row in rows:
            reference[row["symbol"]] = (row["refseq_protein"], row["ensembl_protein"],
                                        row["sequence"])
    return reference


# ------------------------------------------------------------------ parsing
_AA = r"(?:[A-Z][a-z]{2}|[A-Z])"
_RES = rf"({_AA})(\d+)"


def _one_letter(token: str) -> Optional[str]:
    """One-letter code for a residue token, '*' for stop, None if unknown."""
    if token in ("*", "Ter", "TER"):
        return "*"
    if len(token) == 1:
        return token if token in THREE else None
    return ONE.get(token.upper())


def _residues(tokens: str) -> Optional[str]:
    """'HisVal' or 'HV' -> 'HV'; None when any token is not an amino acid."""
    if not tokens:
        return ""
    parts = re.findall(r"[A-Z][a-z]{2}|\*|[A-Z]", tokens)
    if "".join(parts) != tokens:
        return None
    three_letter = all(len(p) == 3 for p in parts)
    if not three_letter and any(len(p) == 3 for p in parts):
        return None
    if not three_letter:
        # One-letter strings can look like three-letter ones only by accident
        # ("Ala" is not valid one-letter), so a mixed read is refused above.
        parts = list(tokens)
    out = [_one_letter(p) for p in parts]
    return None if None in out else "".join(out)


def _parse(text: str) -> Optional[_Parsed]:
    s = text.strip()
    s = re.sub(r"^p\.", "", s)
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    s = s.replace(" ", "")

    m = re.fullmatch(rf"{_RES}_{_RES}(del|dup)", s)
    if m:
        a, b = _one_letter(m[1]), _one_letter(m[3])
        return _Parsed(m[5] if m[5] == "dup" else "deletion",
                       [(a, int(m[2])), (b, int(m[4]))]) if a and b else None
    m = re.fullmatch(rf"{_RES}_{_RES}(ins|delins)([A-Za-z*]+)", s)
    if m:
        a, b, alt = _one_letter(m[1]), _one_letter(m[3]), _residues(m[6])
        if not (a and b and alt):
            return None
        kind = "insertion" if m[5] == "ins" else "delins"
        return _Parsed(kind, [(a, int(m[2])), (b, int(m[4]))], alt)
    m = re.fullmatch(rf"{_RES}delins([A-Za-z*]+)", s)
    if m:
        a, alt = _one_letter(m[1]), _residues(m[3])
        return _Parsed("delins", [(a, int(m[2]))], alt) if a and alt else None
    m = re.fullmatch(rf"{_RES}(del|dup)", s)
    if m:
        a = _one_letter(m[1])
        return _Parsed("deletion" if m[3] == "del" else "dup", [(a, int(m[2]))]) if a else None
    m = re.fullmatch(rf"{_RES}({_AA})?fs((?:\*|Ter)\d+|\*\?|Ter\?)?", s)
    if m:
        a = _one_letter(m[1])
        alt = _one_letter(m[3]) if m[3] else ""
        if not a or alt is None or alt == "*":
            return None
        tail = (m[4] or "").replace("*", "Ter")
        return _Parsed("frameshift", [(a, int(m[2]))], alt, tail)
    m = re.fullmatch(rf"{_RES}(\*|Ter|=|X|Xaa|{_AA})?", s)
    if m:
        a = _one_letter(m[1])
        if not a:
            return None
        token = m[3]
        if token is None:
            return _Parsed("any_change", [(a, int(m[2]))])
        if token == "=":
            return _Parsed("synonymous", [(a, int(m[2]))])
        if token in ("X", "Xaa"):
            return _Parsed("any_substitution", [(a, int(m[2]))])
        alt = _one_letter(token)
        if alt is None:
            return None
        if alt == "*":
            return _Parsed("nonsense", [(a, int(m[2]))], "*")
        if alt == a:
            return _Parsed("synonymous", [(a, int(m[2]))])
        return _Parsed("substitution", [(a, int(m[2]))], alt)
    return None


# ------------------------------------------------------------------ writing
def _three(one: str) -> str:
    return "Ter" if one == "*" else THREE[one]


def _format(p: _Parsed) -> str:
    first = f"{_three(p.residues[0][0])}{p.residues[0][1]}"
    span = first
    if len(p.residues) == 2:
        span = f"{first}_{_three(p.residues[1][0])}{p.residues[1][1]}"
    alt = "".join(_three(c) for c in p.alt)
    if p.kind == "substitution" or p.kind == "nonsense":
        return f"p.{first}{alt}"
    if p.kind == "synonymous":
        return f"p.{first}="
    if p.kind in ("any_change", "any_substitution"):
        # HGVS has no notation for "any change at this residue"; the residue
        # itself is the HGVS reference to it, and `kind` says what is meant.
        return f"p.{first}"
    if p.kind == "deletion":
        return f"p.{span}del"
    if p.kind == "dup":
        return f"p.{span}dup"
    if p.kind == "insertion":
        return f"p.{span}ins{alt}"
    if p.kind == "delins":
        return f"p.{span}delins{alt}"
    if p.kind == "frameshift":
        return f"p.{first}{alt}fs{p.tail}"
    raise ValueError(p.kind)


# ------------------------------------------------------------------ checking
def _is_histone_h3(sequence: str) -> bool:
    return sequence.startswith(_H3_N_TERMINUS)


def normalise(gene: str, stated: str, reference=None) -> ProteinChange:
    """HGVS form of `stated` on `gene`'s MANE Select protein, checked."""
    reference = reference if reference is not None else load_reference()
    result = ProteinChange(stated=stated or "", gene=gene or "", status="unparsed")
    if not (stated or "").strip():
        result.status = "empty"
        return result
    if gene not in reference:
        result.status = "no_reference"
        result.detail = f"{gene} has no MANE Select protein in {os.path.basename(REFERENCE)}"
        return result
    refseq, ensembl, sequence = reference[gene]
    result.refseq_protein, result.ensembl_protein = refseq, ensembl

    parsed = _parse(stated)
    if parsed is None:
        result.detail = "outside the supported notation"
        return result
    result.kind = parsed.kind

    # Three-letter code is HGVS's own notation, so a trial writing it has
    # already numbered from the initiator methionine; only the one-letter
    # literature form is on the mature protein.
    if _is_histone_h3(sequence) and not re.search(r"[A-Z][a-z]{2}\d", stated):
        def fits(residues):
            return all(1 <= p <= len(sequence) and sequence[p - 1] == a for a, p in residues)
        shifted = [(aa, pos + 1) for aa, pos in parsed.residues]
        if fits(shifted) or not fits(parsed.residues):
            parsed.residues = shifted
            result.numbering = "histone_mature"

    for aa, pos in parsed.residues:
        if pos < 1 or pos > len(sequence):
            result.status = "position_out_of_range"
            result.detail = f"position {pos} beyond the {len(sequence)}-residue {refseq}"
            return result
        if sequence[pos - 1] != aa:
            result.status = "reference_mismatch"
            result.detail = (f"{refseq} has {_three(sequence[pos - 1])}{pos}, "
                             f"not {_three(aa)}{pos}")
            return result
    if len(parsed.residues) == 2:
        (_, start), (_, end) = parsed.residues
        if end <= start:
            result.status = "invalid_range"
            result.detail = f"range {start}_{end} does not run forwards"
            return result
        if parsed.kind == "insertion" and end != start + 1:
            result.status = "invalid_range"
            result.detail = f"insertion flanks {start} and {end} are not adjacent"
            return result

    result.hgvs = _format(parsed)
    result.status = VERIFIED
    return result
