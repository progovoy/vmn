#!/usr/bin/env python3
"""The ``text`` signal of similar runs: a run's words, matched with BM25.

A run's *document* is what people wrote about it — its intent (the text, and
each keyword :data:`KEYWORD_REPEAT` times, since a keyword is a deliberate
label), name, note, tags (keys and values), local commit subjects and the
create entry's hypothesis. Changed symbols stay structured signals (see
:mod:`vmn_exp.core.similar_score`), so nothing is counted twice.

Matching is lexical: no stemming, embeddings or model. An agent that wants
synonyms writes them as keywords on its runs, and again into its query.
Pure: no storage.
"""
import math
import re
from collections import Counter

KEYWORD_REPEAT = 3
# BM25's usual constants; QUERY_K3 saturates a term repeated in the query.
K1, B, QUERY_K3 = 1.2, 0.75, 1.5

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been
before being below between both but by can could did do does doing done down
during each else few for from further had has have having he her here hers
him his how i if in into is it its itself just me more most my no nor not now
of off on once only or other our ours out over own same she should so some
such than that the their theirs them then there these they this those through
to too under until up very was we were what when where which while who whom
why will with would you your yours
""".split())

_PIECES = re.compile(r"[\W_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokenize(text):
    """Lowercase words of *text*, split on punctuation, ``_`` and camelCase;
    stopwords and one-character tokens dropped."""
    if not isinstance(text, str):
        return []
    tokens = []
    for piece in _PIECES.split(text):
        for word in _CAMEL.split(piece):
            word = word.lower()
            if len(word) > 1 and word not in STOPWORDS:
                tokens.append(word)
    return tokens


def _strings(value):
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def keyword_phrases(intent):
    """The intent's keywords, lowercased, in their order."""
    return [k.strip().lower() for k in _strings((intent or {}).get("keywords")) if k.strip()]


def document_terms(row, features=None, intent=None, hypothesis=None, create_note=None):
    """The tokens of a run's text document (see the module docstring).

    *create_note* — the first ``create`` entry's note — stands in for a
    missing metadata note.
    """
    row, intent = row or {}, intent or {}
    tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
    parts = [intent.get("text"), row.get("name"), row.get("note") or create_note, hypothesis]
    parts += [str(part) for pair in tags.items() for part in pair]
    parts += _strings((features or {}).get("commits"))
    terms = [term for part in parts for term in tokenize(part)]
    for phrase in keyword_phrases(intent):
        terms += tokenize(phrase) * KEYWORD_REPEAT
    return terms


def query_weights(terms):
    """``{term: weight}`` of a query: 1 for a term said once, saturating as it repeats."""
    return {t: (QUERY_K3 + 1) * n / (QUERY_K3 + n) for t, n in Counter(terms).items()}


class Bm25:
    """BM25 over a corpus of *n_docs* documents of mean length *avg_len*;
    *df(term)* is the number of documents holding *term* (None for none)."""

    def __init__(self, n_docs, avg_len, df):
        self.n_docs, self.avg_len, self._df = n_docs, avg_len or 1.0, df

    def idf(self, term):
        n = self._df(term) or 0
        return math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5))

    def score(self, weights, doc_counts, doc_len):
        """BM25 of one document (its ``Counter`` of terms and length) for the
        query *weights* (:func:`query_weights`)."""
        norm = K1 * (1 - B + B * doc_len / self.avg_len)
        total = 0.0
        for term, weight in weights.items():
            tf = doc_counts.get(term)
            if tf:
                total += weight * self.idf(term) * tf * (K1 + 1) / (tf + norm)
        return total


def shared_reason(query_counts, doc_counts, idf, phrases=(), limit=3):
    """``"shared: a, b, c"`` — keyword *phrases* whose words both sides hold
    first, then shared words by rarity; None when nothing is shared."""
    shared = set(query_counts) & set(doc_counts)
    named, covered = [], set()
    for phrase in (p.strip().lower() for p in phrases):
        words = tokenize(phrase)
        if words and set(words) <= shared and phrase not in named:
            named.append(phrase)
            covered.update(words)
    rest = sorted(shared - covered, key=lambda term: (-idf(term), term))
    named = (named + rest)[:limit]
    return "shared: " + ", ".join(named) if named else None
