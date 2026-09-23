"""
Build ref/mane_select_proteins.tsv: the reference protein sequence every
trial protein change is checked against.

One row per gene: HGNC symbol, HGNC id, MANE Select RefSeq and Ensembl
protein accessions, and the protein sequence. MANE Select is the transcript
VEP reports as CSQ_MANE_SELECT, so a protein change checked here uses the
same numbering as the pipeline's own HGVSp. MANE guarantees that the RefSeq
and Ensembl proteins are identical; this script asserts it rather than
trusting it.

Scope is the Kispi panel (config.GENE_LIST_FILE_PATH) plus every histone H3 gene. Trial
genes outside the panel are dropped upstream by reference validation, and
the H3 genes are needed for the legacy histone numbering in
utils/protein_change.py. Keeping the file to those genes keeps it small
enough to commit, so checking needs no network.

Run once per MANE release. The header records the release and the SHA-256
of every source file, so a checked index can be traced to the exact
sequences it was checked against:

    python -m utils.build_protein_reference --release 1.5
"""
import argparse
import gzip
import hashlib
import os
import sys
import urllib.request

import config
from utils.reference_validation import gene_symbols

BASE = "https://ftp.ncbi.nlm.nih.gov/refseq/MANE/MANE_human/release_{release}/"
FILES = ("MANE.GRCh38.v{release}.summary.txt.gz",
         "MANE.GRCh38.v{release}.refseq_protein.faa.gz",
         "MANE.GRCh38.v{release}.ensembl_protein.faa.gz")
OUT = config.PROTEIN_REFERENCE_FILE_PATH
COLUMNS = ["symbol", "hgnc_id", "refseq_protein", "ensembl_protein", "sequence"]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _fasta(path):
    sequences, key, chunks = {}, None, []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if line.startswith(">"):
                if key:
                    sequences[key] = "".join(chunks)
                key, chunks = line[1:].split()[0], []
            else:
                chunks.append(line.strip())
    if key:
        sequences[key] = "".join(chunks)
    return sequences


def build(release, source_dir, out=OUT):
    paths = []
    for template in FILES:
        name = template.format(release=release)
        path = os.path.join(source_dir, name)
        if not os.path.exists(path):
            url = BASE.format(release=release) + name
            print(f"fetching {url}", file=sys.stderr)
            urllib.request.urlretrieve(url, path)
        paths.append(path)
    summary_path, refseq_path, ensembl_path = paths

    wanted = gene_symbols()
    panel = config.GENE_LIST_FILE_PATH
    select = {}
    with gzip.open(summary_path, "rt") as handle:
        header = handle.readline().lstrip("#").rstrip("\n").split("\t")
        for line in handle:
            row = dict(zip(header, line.rstrip("\n").split("\t")))
            if row["MANE_status"] == "MANE Select":
                select[row["symbol"]] = row
    # Non-coding genes (PVT1, TERC, ...) have a MANE transcript but no
    # protein, so no protein change can be checked against them.
    noncoding = sorted(s for s in wanted if s in select and not select[s]["RefSeq_prot"])
    select = {s: r for s, r in select.items() if r["RefSeq_prot"]}
    histone_h3 = {s for s in select if s.startswith(("H3-", "H3C"))}

    refseq, ensembl = _fasta(refseq_path), _fasta(ensembl_path)
    rows, missing = [], sorted(wanted - set(select) - set(noncoding))
    for symbol in sorted((wanted | histone_h3) & set(select)):
        row = select[symbol]
        sequence = refseq[row["RefSeq_prot"]]
        if ensembl[row["Ensembl_prot"]] != sequence:
            raise SystemExit(f"{symbol}: RefSeq and Ensembl MANE proteins differ")
        rows.append([symbol, row["HGNC_ID"], row["RefSeq_prot"], row["Ensembl_prot"], sequence])

    with open(out, "w") as handle:
        handle.write(f"# MANE Select GRCh38 v{release} protein sequences; "
                     f"panel {panel} plus histone H3 genes\n")
        for path in paths:
            handle.write(f"# source {os.path.basename(path)} sha256 {_sha256(path)}\n")
        handle.write(f"# panel genes without a MANE Select transcript: {', '.join(missing) or 'none'}\n")
        handle.write(f"# panel genes that are non-coding (no protein): {', '.join(noncoding) or 'none'}\n")
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
    return len(rows), missing


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release", required=True, help="MANE release, e.g. 1.5")
    parser.add_argument("--source-dir", default="cache/mane",
                        help="where the MANE files are kept or downloaded to")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    os.makedirs(args.source_dir, exist_ok=True)
    n, missing = build(args.release, args.source_dir, args.out)
    print(f"{n} genes written to {args.out}; {len(missing)} panel genes have no MANE Select")


if __name__ == "__main__":
    main()
