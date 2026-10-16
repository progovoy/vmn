#!/usr/bin/env python3
"""``similar("<text>")`` in the query language (plan 24 F5).

A run matches when the ``text`` column of its similar-runs FTS5 document
(:mod:`vmn_exp.core.similar_fts`: its intent text and keywords, name, note,
hypothesis and commit subjects) holds **every** word of *text*. The words
are :func:`~vmn_exp.core.similar_match.words`' (lowercased runs of letters
and digits); each becomes a quoted FTS5 string — never query syntax, so
``"``, ``*``, ``:``, ``NEAR`` or ``OR`` in the text are only words — that the
table's ``porter unicode61`` tokenizer stems (``losses`` finds ``loss``).
They are ANDed: a filter, not a ranking, so there is no score threshold and
no stopword list (``similar("the loss")`` needs a ``the``).

A query is resolved once per distinct text, over the
:class:`~vmn_exp.core.similar_corpus.Scope` a caller supplies
(:mod:`vmn_exp.core.query_extra`).
"""
import functools

from vmn_exp.core import similar_fts
from vmn_exp.core.query import SIMILAR, QueryError
from vmn_exp.core.similar_match import quoted, words

NO_INDEX = "similar() needs the persisted index of an app's runs; this listing has none"
NO_FTS5 = "similar() needs SQLite with FTS5 (python's sqlite3 lacks it)"


def expression(text):
    """The FTS5 MATCH expression of *text*: every word in the ``text`` column;
    None without a word."""
    return " AND ".join(f"text : {quoted(w)}" for w in words(text)) or None


def matching(scope, text):
    """The verstrs of *scope*'s app whose text document holds every word of *text*."""
    found = expression(text)
    if found is None:
        return set()
    with scope.lock:
        return {verstr for (verstr,) in scope.conn.execute(
            "SELECT verstr FROM similar_fts WHERE similar_fts MATCH ? AND app = ?",
            (found, scope.app))}


def scope_matcher(scope_of):
    """``text -> verstrs`` over the scope ``scope_of()`` returns, opened at
    the first text asked; a :class:`QueryError` without FTS5 or a scope."""
    opened = functools.lru_cache(maxsize=None)(scope_of)

    def match(text):
        try:
            scope = opened()
        except similar_fts.Fts5Missing:
            raise QueryError(NO_FTS5) from None
        if scope is None:
            raise QueryError(NO_INDEX)
        return matching(scope, text)

    return match


def similar_texts(node, found=None):
    """The distinct ``similar()`` texts of the query AST *node*, in order."""
    found = {} if found is None else found
    if node[0] == SIMILAR:
        found.setdefault(node[1])
    elif node[0] in ("and", "or"):
        for term in node[1]:
            similar_texts(term, found)
    elif node[0] == "not":
        similar_texts(node[1], found)
    return list(found)


def similar_hits(tree, extra):
    """``verstr -> the similar() texts it matches`` of the query AST *tree*,
    each text resolved once by ``extra["similar"]``."""
    resolve = (extra or {}).get(SIMILAR)
    if resolve is None:
        raise QueryError(NO_INDEX)
    hits = {text: frozenset(resolve(text)) for text in similar_texts(tree)}
    return lambda verstr: frozenset(t for t, found in hits.items() if verstr in found)
