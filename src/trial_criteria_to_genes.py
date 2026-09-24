# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

import re
from collections.abc import Iterable, Mapping

from loguru import logger

try:
    import src.trial_config as _config
except ImportError:  # pragma: no cover - allows standalone import in tests
    _config = None


class TrialCriteriaToGenes:
    """
    Extract official gene symbols from free-text trial criteria.

    Accepts a pre-loaded synonym mapping:
    - synonym_to_symbol: maps any synonym (including addendum entries) -> official symbol
    """

    def __init__(
        self,
        trial_criteria: str,
        synonym_to_symbol: Mapping[str, str | Iterable[str]],
    ):
        self.trial_criteria = trial_criteria or ""
        self.synonym_to_symbol = synonym_to_symbol
        self.blocked = {
            b.upper() for b in getattr(_config, 'blocked_gene_synonyms', [])
        }
        self.contextual = getattr(_config, 'contextual_gene_synonyms', {}) or {}
        self._criteria_lower = self.trial_criteria.lower()

    # Joiners that put two gene names into one whitespace token: fusion
    # notation (PICALM::MLLT10, BCR-ABL1, P2RY8-CRLF2, with a hyphen or an
    # en/em dash) and unspaced lists (FLT3/ITD, IDH1/2, ASXL1/2). On the 55
    # reviewed trials the whole-token scan missed curated genes in 12 of them,
    # 11 because of these joiners (the twelfth writes a gene only as a
    # t(15;17)/inv(16) karyotype).
    _JOINERS = re.compile(r"::|[-/,;\u2010\u2011\u2012\u2013\u2014\u2212]")

    @staticmethod
    def _normalize_token(s: str) -> str:
        s = (s or "").strip()
        s = s.strip('"\',;:.()[]{}')
        return s

    @staticmethod
    def _as_list(v: str | Iterable[str] | None) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [x for x in v if x is not None]

    @classmethod
    def _generate_candidates(cls, words: list[str], max_ngram: int = 4) -> list[str]:
        """
        Build candidate phrases (n-grams) from normalized tokens.
        Longest n-grams are generated first so multi-word addendum keys can match early.
        """
        candidates: list[str] = []
        n_max = max(1, int(max_ngram))
        for n in range(min(n_max, len(words)), 0, -1):
            for i in range(0, len(words) - n + 1):
                candidates.append(" ".join(words[i : i + n]))

        # De-dupe while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for c in candidates:
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
        return out

    def tokenize_trial_criteria(self, max_ngram: int = 4) -> list[str]:
        """
        tokenization of the trial criteria
        """
        tokens_raw = (self.trial_criteria or "").split()
        words = [w for w in (self._normalize_token(t) for t in tokens_raw) if w]

        #words = self._generate_candidates(words, max_ngram=max_ngram)
        return words

    def _lookup_official_symbols(self, token: str) -> list[str]:
        """
        Lookup a token in the synonym mapping.

        Blocked synonyms never resolve via the NCBI-derived table, because in
        trial criteria they overwhelmingly mean something other than the gene.
        A blocked synonym may still resolve through a context rule, which
        requires supporting keywords to appear in the criteria text.
        """
        upper = token.upper()

        rule = self.contextual.get(upper) or self.contextual.get(token)
        if rule:
            keywords, symbols = rule
            if any(k.lower() in self._criteria_lower for k in keywords):
                logger.debug(f"Context mapping for token: {token} : {symbols}")
                return list(symbols)
            # Context absent - fall through to the block check below.

        if upper in self.blocked:
            logger.debug(f"Blocked ambiguous synonym: {token} "
                  f"(would have mapped to {self._as_list(self.synonym_to_symbol.get(token))})")
            return []

        if token in self.synonym_to_symbol:
            logger.debug(f"Found mapping for token: {token} : {self.synonym_to_symbol[token]}")
            return self._as_list(self.synonym_to_symbol[token])
        return []

    def _is_official(self, symbol: str) -> bool:
        """True for a current symbol: the mapping lists every one as its own alias."""
        return symbol in self._as_list(self.synonym_to_symbol.get(symbol))

    def _part_tokens(self, token: str) -> list[str]:
        """
        The gene names joined inside one token, beyond the token itself.

        A part must still resolve through the synonym mapping, and a part of
        three characters or fewer counts only if it is itself a current symbol
        (DEK, SET, WT1). Short aliases do not: splitting "CAR-T" would
        otherwise turn CAR into PRKAR1A, "AT/RT" AT into BTK, "B-ALL" ALL into
        BCR, and "p14/ARF" ARF into CDKN2A - collisions the whole-token scan
        never made because those aliases never stood alone.

        A one- or two-character part after a slash is the shorthand for a
        sibling gene: IDH1/2, ASXL1/2, CDKN2A/B, JAK1/2/3, MYC/N. It is
        expanded against the first part (replace its tail, or append), and
        kept only when the result is a current symbol, so "MYC/N" gives MYCN
        and never MYN, which is an alias of PALLD.

        A lower-case "c" before a current symbol of three or more letters is
        the proto-oncogene prefix (cCBL in NCT05658640, cMYC, cKIT) and yields
        that symbol.
        """
        # ClinicalTrials.gov stores markdown, so "[ERG]" arrives as "\\[ERG\\]"
        # and the whole token never matched (NCT07297979 lost ERG to it). The
        # unescaped token is held to the same short-alias rule as a part:
        # "\\[SF\\]" (shortening fraction, NCT05183035) would otherwise
        # resolve SF to HGF.
        cleaned = self._normalize_token(token.replace("\\", ""))
        parts = [self._normalize_token(p) for p in self._JOINERS.split(cleaned)]
        parts = [p for p in parts if p]
        candidates = [cleaned] if cleaned and cleaned != token else []
        if len(parts) > 1:
            candidates.extend(parts)
        out = [p for p in candidates if len(p) > 3 or self._is_official(p)]
        if len(parts) > 1:
            base = parts[0]
            if "/" in cleaned and self._is_official(base):
                for p in parts[1:]:
                    if len(p) <= 2 and p.isalnum():
                        for cand in (base[:-len(p)] + p, base + p):
                            if cand != base and self._is_official(cand):
                                out.append(cand)
                                break
        for p in parts or [cleaned]:
            if len(p) >= 4 and p[0] == "c" and p[1:].isupper() and self._is_official(p[1:]):
                out.append(p[1:])
        return out

    def extract_official_gene_symbols(self) -> list[str]:
        """
        Returns a de-duplicated list of official gene symbols found in the criteria.

        Each whitespace token is looked up whole (so addendum keys such as
        "KRAS/NRAS/HRAS" and "RAS-mutated" still match), then its joined
        parts are looked up too (see _part_tokens). On the 55 reviewed trials
        this cut trials with a curated gene missing from the list from 12 to
        2 and added no gene that is not named in the text.
        """
        tokens = []
        for tok in self.tokenize_trial_criteria():
            tokens.append(tok)
            tokens.extend(self._part_tokens(tok))

        found: set[str] = set[str]()
        for tok in tokens:
            official_symbols = self._lookup_official_symbols(tok)
            if len(official_symbols) > 0:
                # Each value can itself be a comma-separated list of symbols,
                # e.g. "KRAS,NRAS,HRAS". Split, normalize, and add individually.
                for val in official_symbols:
                    for part in val.split(","):
                        norm = self._normalize_token(part)
                        if norm:
                            found.add(norm)

        # Sorted: a set's order follows PYTHONHASHSEED, and this list is
        # printed into the genomic prompts (roadmap 1.9).
        return sorted(found)