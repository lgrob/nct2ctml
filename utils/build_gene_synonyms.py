"""
Rebuild ref/synonym_to_gene_symbol.tsv from NCBI Gene.

The checked-in synonym table is an undated snapshot of unknown provenance, and
it has drifted from NCBI: it maps H3, H4 and H5 to FGFR1, none of which current
NCBI lists as an FGFR1 alias, while missing every post-2019 HGNC histone
symbol (H3-3A, H3C2, ...).
This script regenerates it from a live source so the mapping is dated,
auditable and refreshable.

Regenerating does NOT by itself fix the mapping. NCBI's OtherAliases is a
historical synonym field, not a disambiguated oncology lexicon: BCR genuinely
lists ALL as an alias, BRD4 lists CAP, CCDC6 lists H4, SEPTIN5 lists H5. Those
are correct as history and wrong as an oncology lookup, so blocked_gene_synonyms
in src/trial_config.py is still required after regenerating. What the script adds is that building
gene -> aliases and then inverting makes such problems *detectable*: every
alias claimed by more than one gene, or claimed by one gene while being
another's official symbol, is written to a collisions report for review rather
than silently entering the mapping.

Usage:
    python -m utils.build_gene_synonyms [--api-key KEY] [--email ADDR]
                                        [--genes ref/genes.txt] [--limit N]

An NCBI API key raises the rate limit from 3 to 10 requests/second; get one at
https://www.ncbi.nlm.nih.gov/account/. Without one the full run takes ~5
minutes. Responses are cached, so re-runs are near-instant and only fetch
genes not seen before.

Outputs (written next to the existing table, never over it):
    ref/synonym_to_gene_symbol.generated.tsv  the new mapping
    ref/synonym_collisions.tsv                ambiguous aliases, for review
    ref/.ncbi_gene_cache.json                 raw NCBI responses
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict

import requests
from loguru import logger

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "nct2ctml"
CACHE_PATH = "ref/.ncbi_gene_cache.json"
DEFAULT_GENES = "ref/genes.txt"
OUT_MAPPING = "ref/synonym_to_gene_symbol.generated.tsv"
OUT_COLLISIONS = "ref/synonym_collisions.tsv"

# esummary accepts many ids at once; esearch is one call per symbol.
ESUMMARY_BATCH = 200


class NcbiClient:
    """Minimal eutils client with the rate limit and retries NCBI expects."""

    def __init__(self, email: str, api_key: str | None = None):
        self.email = email
        self.api_key = api_key
        # NCBI permits 10 requests/second with a key, 3 without. Stay just
        # under, since exceeding it gets the calling IP blocked rather than
        # throttled.
        self.min_interval = 0.11 if api_key else 0.36
        self._last = 0.0
        self.session = requests.Session()

    def _wait(self):
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()

    def get(self, endpoint: str, params: dict, attempts: int = 4) -> dict | None:
        params = {**params, "retmode": "json", "tool": TOOL, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key

        for attempt in range(attempts):
            self._wait()
            try:
                r = self.session.get(f"{EUTILS}/{endpoint}", params=params, timeout=60)
                if r.status_code == 429:
                    raise requests.HTTPError("rate limited")
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                backoff = 2 ** attempt
                if attempt == attempts - 1:
                    logger.error(f"{endpoint} failed after {attempts} attempts: {e}")
                    return None
                logger.warning(f"{endpoint} attempt {attempt + 1} failed ({e}); retrying in {backoff}s")
                time.sleep(backoff)
        return None


def load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            logger.warning(f"Could not read {CACHE_PATH}; starting a fresh cache")
    return {}


def save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)


def find_gene_ids(client: NcbiClient, symbol: str) -> list[str]:
    """
    Candidate NCBI gene ids for one symbol.

    A [Gene Name] search can match several loci - paralogs, withdrawn records,
    read-through transcripts - and merging their aliases would conflate
    distinct genes. Only ids are returned here; the caller keeps the record
    whose official symbol matches, so a wrong locus is dropped, not blended in.
    """
    data = client.get("esearch.fcgi", {
        "db": "gene",
        "term": f"{symbol}[Gene Name] AND Homo sapiens[Organism] AND alive[Property]",
    })
    if not data:
        return []
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_summaries(client: NcbiClient, gene_ids: list[str]) -> dict:
    """Batch esummary so one request covers up to ESUMMARY_BATCH genes."""
    out = {}
    for i in range(0, len(gene_ids), ESUMMARY_BATCH):
        chunk = gene_ids[i:i + ESUMMARY_BATCH]
        data = client.get("esummary.fcgi", {"db": "gene", "id": ",".join(chunk)})
        if not data:
            continue
        result = data.get("result", {})
        for gid in chunk:
            if gid in result:
                out[gid] = result[gid]
        logger.info(f"fetched summaries {i + len(chunk)}/{len(gene_ids)}")
    return out


def harvest(client: NcbiClient, symbols: list[str], cache: dict) -> dict:
    """Return {queried_symbol: {official, aliases, gene_id}} for every symbol."""
    pending = [s for s in symbols if s not in cache]
    logger.info(f"{len(symbols)} symbols requested, {len(pending)} not cached")

    # Phase 1: symbol -> candidate gene ids
    symbol_ids: dict[str, list[str]] = {}
    for n, sym in enumerate(pending, 1):
        symbol_ids[sym] = find_gene_ids(client, sym)
        if n % 50 == 0 or n == len(pending):
            logger.info(f"resolved {n}/{len(pending)} symbols to gene ids")

    # Phase 2: one batched esummary for every candidate id
    all_ids = sorted({gid for ids in symbol_ids.values() for gid in ids})
    summaries = fetch_summaries(client, all_ids) if all_ids else {}

    # Phase 3: pick the record whose official symbol matches the query
    for sym, ids in symbol_ids.items():
        chosen = None
        for gid in ids:
            doc = summaries.get(gid)
            if not doc:
                continue
            official = (doc.get("nomenclaturesymbol") or doc.get("name") or "").strip()
            if official.upper() == sym.upper():
                chosen = (gid, doc)
                break
        if chosen is None and ids:
            # No exact match: the query was probably a legacy symbol, so take
            # the first live record and record its current official symbol.
            gid = ids[0]
            if gid in summaries:
                chosen = (gid, summaries[gid])
        if chosen is None:
            logger.warning(f"No NCBI gene record for {sym}")
            cache[sym] = {"official": None, "aliases": [], "gene_id": None}
            continue

        gid, doc = chosen
        official = (doc.get("nomenclaturesymbol") or doc.get("name") or sym).strip()
        raw = doc.get("otheraliases") or ""
        aliases = [a.strip() for a in raw.split(",") if a.strip()]
        cache[sym] = {"official": official, "aliases": aliases, "gene_id": gid}

    return cache


def invert(records: dict, symbols: list[str]) -> tuple[dict, list]:
    """
    Build alias -> official symbol, collecting collisions instead of hiding them.

    An alias claimed by several genes (IDH -> IDH1 and IDH2) is genuinely
    ambiguous and is quarantined. An alias that is itself one of those genes'
    official symbols (HGF, also a historical alias of IL6 and SOS1) is not:
    the gene's own name wins.
    """
    official_symbols = {r["official"] for r in records.values() if r.get("official")}
    official_symbols |= set(symbols)
    # A legacy symbol that NCBI has renamed is not a collision: HIST1H3B ->
    # H3C2 is the same gene under its current name, and that mapping is
    # precisely what keeps pre-2019 criteria text matching. Only treat an
    # alias as colliding when it identifies a *different* gene.
    renamed_to = {q: r["official"] for q, r in records.items() if r.get("official")}

    alias_to_genes: dict[str, set] = defaultdict(set)
    for queried, rec in records.items():
        official = rec.get("official")
        if not official:
            continue
        # The queried symbol and the current official symbol both resolve to
        # the official one, which is what keeps legacy names working after a
        # nomenclature change (HIST1H3B and H3C2 both -> the same gene).
        for name in {queried, official, *rec.get("aliases", [])}:
            if name:
                alias_to_genes[name].add(official)

    mapping, collisions = {}, []
    for alias, genes in sorted(alias_to_genes.items()):
        genes = sorted(genes)
        if len(genes) > 1:
            # An alias that is itself one of the candidate official symbols is
            # not ambiguous: HGF is listed as a historical alias of IL6 and
            # SOS1, but text saying "HGF" means the HGF gene. The gene's own
            # name wins, and the historical claims are discarded. Without this
            # the gene becomes unfindable by its own symbol.
            if alias in genes:
                mapping[alias] = alias
                continue
            collisions.append((alias, genes, "claimed by multiple genes"))
            continue
        gene = genes[0]
        is_rename = renamed_to.get(alias) == gene
        if alias != gene and alias in official_symbols and not is_rename:
            collisions.append((alias, [gene], f"alias is also the official symbol {alias}"))
            continue
        mapping[alias] = gene
    return mapping, collisions


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"),
                    help="NCBI API key (or set NCBI_API_KEY). Raises the rate limit 3->10/s.")
    ap.add_argument("--email", default=os.environ.get("NCBI_EMAIL"),
                    help="Contact address NCBI requires (or set NCBI_EMAIL).")
    ap.add_argument("--genes", default=DEFAULT_GENES, help=f"Symbol list (default {DEFAULT_GENES})")
    ap.add_argument("--limit", type=int, help="Only process the first N symbols, for a trial run.")
    args = ap.parse_args()

    if not args.email:
        sys.exit("An email address is required: pass --email or set NCBI_EMAIL. "
                 "NCBI uses it to contact you before blocking abusive traffic.")

    with open(args.genes) as f:
        symbols = [line.strip() for line in f if line.strip()]
    if args.limit:
        symbols = symbols[:args.limit]

    client = NcbiClient(email=args.email, api_key=args.api_key)
    logger.info(f"rate limit {'10/s (api key)' if args.api_key else '3/s (no api key)'}")

    cache = load_cache()
    try:
        cache = harvest(client, symbols, cache)
    finally:
        save_cache(cache)
        logger.info(f"cache written to {CACHE_PATH}")

    records = {s: cache[s] for s in symbols if s in cache}
    mapping, collisions = invert(records, symbols)

    with open(OUT_MAPPING, "w") as f:
        for alias, gene in sorted(mapping.items()):
            f.write(f"{alias}\t{gene}\n")
    with open(OUT_COLLISIONS, "w") as f:
        f.write("alias\tcandidate_symbols\treason\n")
        for alias, genes, reason in collisions:
            f.write(f"{alias}\t{','.join(genes)}\t{reason}\n")

    renamed = [(s, r["official"]) for s, r in records.items()
               if r.get("official") and r["official"].upper() != s.upper()]

    print(f"\nsymbols processed      : {len(records)}")
    print(f"unresolved             : {sum(1 for r in records.values() if not r.get('official'))}")
    print(f"aliases written        : {len(mapping)}  -> {OUT_MAPPING}")
    print(f"collisions quarantined : {len(collisions)}  -> {OUT_COLLISIONS}")
    print(f"symbols NCBI has renamed since genes.txt was built: {len(renamed)}")
    for old, new in renamed[:10]:
        print(f"    {old} -> {new}")
    if collisions:
        print("\nfirst collisions (review these, then add to blocked_gene_synonyms "
              "or contextual_gene_synonyms in src/trial_config.py):")
        for alias, genes, reason in collisions[:10]:
            print(f"    {alias:<12} {','.join(genes):<24} {reason}")
    print(f"\nNothing was overwritten. Diff {OUT_MAPPING} against "
          f"ref/synonym_to_gene_symbol.tsv before adopting it.")


if __name__ == "__main__":
    main()
