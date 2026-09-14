# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

# One-time script that built the original ref/synonym_to_gene_symbol.tsv from
# the COSMIC Cancer Gene Census. Superseded by utils/build_gene_synonyms.py,
# which harvests aliases live from NCBI Gene and reports ambiguous ones.
#
# ref/Census_gene_list.csv is no longer tracked - the COSMIC licence restricts
# redistribution - so this script only runs if you download the Census
# yourself from https://cancer.sanger.ac.uk/census and place it there.
import pandas as pd

df = pd.read_csv("../ref/Census_gene_list.csv", dtype=str).fillna("")

df = df[["Gene Symbol", "Synonyms"]].rename(columns={"Gene Symbol": "official"})

# split the comma-separated synonym cell into many rows
df["synonym"] = df["Synonyms"].str.split(",")
df = df.explode("synonym", ignore_index=True)

# clean
df["synonym"] = df["synonym"].str.strip().str.strip('"').str.strip()
df["official"] = df["official"].str.strip()

# also map the official symbol to itself
self_map = df[["official"]].drop_duplicates().assign(synonym=lambda x: x["official"])
df = pd.concat([df[["synonym", "official"]], self_map[["synonym", "official"]]], ignore_index=True)

# drop empties + duplicates
df = df[(df["synonym"] != "") & (df["official"] != "")]
df = df.drop_duplicates()

# write to a TSV
df.to_csv("../ref/synonym_to_gene_symbol.tsv", sep="\t", index=False, header=False)