"""Tool search strategies for on-demand deferred tool loading.

Provides a pluggable search interface so strategies can be swapped
without touching the registry or tool infrastructure.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from proxi.tools.base import Tool


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into alphanumeric tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class ToolSearchEntry:
    """Index entry for a single deferred tool."""

    tool: "Tool"
    corpus: str = field(repr=False)  # lowercased "name description"
    tokens: list[str] = field(repr=False)  # tokenized corpus for BM25


def build_index(tools: "list[Tool]") -> list[ToolSearchEntry]:
    """Build a search index from a list of tools."""
    entries: list[ToolSearchEntry] = []
    for t in tools:
        corpus = f"{t.name} {t.description}".lower()
        entries.append(ToolSearchEntry(tool=t, corpus=corpus, tokens=_tokenize(corpus)))
    return entries


class ToolSearchStrategy(Protocol):
    """Protocol for pluggable tool search strategies."""

    def search(
        self,
        query: str,
        entries: list[ToolSearchEntry],
        top_k: int,
    ) -> "list[Tool]":
        """Return up to top_k tools ranked by relevance to query."""
        ...


class RegexSearchStrategy:
    """Simple substring / keyword search strategy.

    Splits the query on whitespace and counts how many tokens appear as
    substrings in each entry's corpus. Entries are ranked by hit count.
    No external dependencies.
    """

    def search(
        self,
        query: str,
        entries: list[ToolSearchEntry],
        top_k: int,
    ) -> "list[Tool]":
        if not entries:
            return []
        tokens = query.lower().split()
        if not tokens:
            return []

        scored: list[tuple[int, "Tool"]] = []
        for entry in entries:
            hits = sum(1 for t in tokens if t in entry.corpus)
            if hits > 0:
                scored.append((hits, entry.tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in scored[:top_k]]


class BM25SearchStrategy:
    """Okapi BM25 search strategy.

    Pure Python implementation — no external dependencies. Suitable for
    small corpora (<500 tools). IDF and avgdl are recomputed per call,
    which is fast enough at this scale.

    Parameters
    ----------
    k1:
        Term-frequency saturation parameter (default 1.5).
    b:
        Length normalisation parameter (default 0.75).
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def search(
        self,
        query: str,
        entries: list[ToolSearchEntry],
        top_k: int,
    ) -> "list[Tool]":
        if not entries:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        N = len(entries)
        avgdl = sum(len(e.tokens) for e in entries) / N

        # Document frequency for each unique token across the corpus
        df: dict[str, int] = {}
        for entry in entries:
            for token in set(entry.tokens):
                df[token] = df.get(token, 0) + 1

        scores: list[tuple[float, "Tool"]] = []
        for entry in entries:
            dl = len(entry.tokens)
            tf_dict: dict[str, int] = {}
            for tok in entry.tokens:
                tf_dict[tok] = tf_dict.get(tok, 0) + 1

            score = 0.0
            for token in query_tokens:
                if token not in df:
                    continue
                tf = tf_dict.get(token, 0)
                idf = math.log((N - df[token] + 0.5) / (df[token] + 0.5) + 1)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / avgdl)
                tf_norm = (tf * (self.k1 + 1)) / denom if denom else 0.0
                score += idf * tf_norm

            if score > 0:
                scores.append((score, entry.tool))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in scores[:top_k]]
