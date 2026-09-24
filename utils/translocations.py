"""
Cytogenetic rearrangements in trial text, turned into gene pairs by a curated
table - no model involved.

Trials write fusions in ISCN notation as often as in gene names: 44 cached
trials mention one, as t(9;22), inv(16), t (X; 18) or t(12; 22) (q13;q12). The
genomic prompt is told not to derive genes from that notation (rule 9),
because the model gets it wrong in exactly the ambiguous cases. This module
does the translation deterministically instead:

- `find(text)` parses every rearrangement in the text: t(), inv() and
  their spacing, colon and comma variants, with bands when given.
- `resolve(r)` looks it up in ref/translocation_fusions.tsv
  (config.TRANSLOCATION_TABLE_FILE_PATH).

Resolution rules, in order. Nothing is guessed:

1. **Bands given:** a row whose bands match at arm + major band (q34.1 ->
   q34) is taken. If none matches, the result is unresolved, not the bare
   reading, because bands that disagree with it are information.
2. **No bands, exactly one bare row:** that row, the conventional reading
   (inv(16) -> CBFB::MYH11).
3. **No bands, several rows:** the one gene every candidate shares, with no
   partner (t(8;14) -> MYC, from IGH::MYC or TRA::MYC). If none is shared,
   the result is unresolved (t(12;22): EWSR1::DDIT3 or MN1::ETV6).

What this does NOT decide is whether a rearrangement mentioned in a trial is a
criterion. In 9 of the 11 reviewed trials that mention one, the curator made
no gene criterion of it: they are risk-group definitions and lists of
examples. That judgement stays with the model and the reviewer. This module
supplies evidence: which genes a text names in cytogenetic form.
"""
import csv
import re
from dataclasses import dataclass
from functools import lru_cache

import config

_CHROM = r"(?:[0-9]{1,2}|[XYxy])"
_BAND = r"[pq]\s*[0-9]+(?:\.[0-9]+)?(?:\s*-\s*[0-9]+(?:\.[0-9]+)?)?"
_PATTERN = re.compile(
    r"(?<![A-Za-z])(?P<kind>t|inv)\s*\(\s*(?P<c1>" + _CHROM + r")\s*(?:[;:,]\s*(?P<c2>" + _CHROM + r"))?\s*\)"
    r"(?:\s*\(\s*(?P<b1>" + _BAND + r")\s*[;:,]?\s*(?P<b2>" + _BAND + r")\s*\))?")


@dataclass(frozen=True)
class Rearrangement:
    notation: str          # canonical, e.g. "t(9;22)" or "inv(16)"
    bands: tuple           # canonical major bands, e.g. ("q34", "q11"), or ()
    text: str              # as written


@dataclass(frozen=True)
class Resolution:
    gene_a: str = ""
    gene_b: str = ""       # "" when gene-level only
    status: str = ""       # "resolved" | "gene_level" | "unresolved"
    detail: str = ""


def _major(band):
    band = re.sub(r"\s", "", band.lower())
    m = re.match(r"([pq])(\d+)", band)
    return f"{m.group(1)}{m.group(2)}" if m else band


def _chrom_key(c):
    c = c.upper()
    return (0, c) if c in ("X", "Y") else (1, int(c))


def _canonical(kind, c1, c2, b1, b2):
    kind = kind.lower()
    bands = tuple(_major(b) for b in (b1, b2) if b)
    if kind == "inv" or not c2:
        return f"{kind}({c1.upper()})", bands
    pairs = [(c1.upper(), bands[0] if bands else ""), (c2.upper(), bands[1] if len(bands) > 1 else "")]
    if _chrom_key(pairs[0][0]) > _chrom_key(pairs[1][0]):
        pairs.reverse()
    notation = f"t({pairs[0][0]};{pairs[1][0]})"
    return notation, tuple(b for _, b in pairs) if len(bands) == 2 else ()


def find(text):
    """Every t()/inv() rearrangement in `text`, in order of appearance."""
    out = []
    for m in _PATTERN.finditer(text or ""):
        if m.group("kind").lower() == "t" and not m.group("c2"):
            continue                      # "t(9)" is not a translocation
        notation, bands = _canonical(m.group("kind"), m.group("c1"), m.group("c2"),
                                     m.group("b1"), m.group("b2"))
        out.append(Rearrangement(notation, bands, m.group(0)))
    return out


@lru_cache(maxsize=1)
def table():
    """
    {notation: [(bands, gene_a, gene_b, reason)]}. Each row is parsed with
    the same parser as trial text, so a row and a trial writing the same
    thing always agree. A row that does not parse is an error, not a skip.
    """
    rows = {}
    with open(config.TRANSLOCATION_TABLE_FILE_PATH, newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    for row in csv.DictReader(lines, delimiter="\t"):
        written = row["notation"] + (f"({row['bands']})" if row["bands"].strip() else "")
        parsed = find(written)
        if len(parsed) != 1 or (row["bands"].strip() and not parsed[0].bands):
            raise ValueError(f"translocation table row does not parse: {written!r}")
        rows.setdefault(parsed[0].notation, []).append(
            (parsed[0].bands, row["gene_a"].strip(), row["gene_b"].strip(), row["reason"].strip()))
    return rows


def _from_row(row, how):
    _, a, b, _ = row
    return Resolution(a, b, "resolved" if b else "gene_level", how)


def resolve(r):
    candidates = table().get(r.notation, [])
    if not candidates:
        return Resolution(status="unresolved", detail=f"{r.notation} is not in the table")
    if r.bands:
        hits = [c for c in candidates if c[0] == r.bands]
        if len(hits) == 1:
            return _from_row(hits[0], f"{r.notation}({';'.join(r.bands)})")
        return Resolution(status="unresolved",
                          detail=f"{r.text}: bands {';'.join(r.bands)} match no row for {r.notation}")
    bare = [c for c in candidates if not c[0]]
    if len(bare) == 1:
        return _from_row(bare[0], f"{r.notation}, conventional reading")
    genes = [{c[1], c[2]} - {""} for c in candidates]
    shared = set.intersection(*genes) if genes else set()
    if len(shared) == 1:
        return Resolution(shared.pop(), "", "gene_level",
                          f"{r.notation} without bands: partner ambiguous")
    return Resolution(status="unresolved", detail=f"{r.notation} without bands is ambiguous")


def genes_in(text):
    """
    {gene: [evidence]} for every gene a resolved rearrangement in `text`
    names. This is evidence that the text names the gene; it says nothing
    about whether the trial requires it.
    """
    out = {}
    for r in find(text):
        res = resolve(r)
        for g in (res.gene_a, res.gene_b):
            if g:
                out.setdefault(g, []).append(f"{r.text.strip()} -> {res.gene_a}"
                                             + (f"::{res.gene_b}" if res.gene_b else ""))
    return out
