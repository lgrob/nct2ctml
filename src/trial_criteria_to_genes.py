# Modified by Kinderspital Zurich (Kispi) from the original
# nct2ctml, Copyright 2026 The University of Hong Kong, Apache-2.0.
# Retargeted from adult oncology in Hong Kong to paediatric oncology.
# See CHANGES.md for what differs.

from collections.abc import Iterable, Mapping

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
                print(f"Context mapping for token: {token} : {symbols}")
                return list(symbols)
            # Context absent - fall through to the block check below.

        if upper in self.blocked:
            print(f"Blocked ambiguous synonym: {token} "
                  f"(would have mapped to {self._as_list(self.synonym_to_symbol.get(token))})")
            return []

        if token in self.synonym_to_symbol:
            print(f"Found mapping for token: {token} : {self.synonym_to_symbol[token]}")
            return self._as_list(self.synonym_to_symbol[token])
        return []

    def extract_official_gene_symbols(self) -> list[str]:
        """
        Returns a de-duplicated list of official gene symbols found in the criteria.
        """
        tokens = self.tokenize_trial_criteria()

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

        return list[str](found)