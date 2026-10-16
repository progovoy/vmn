#!/usr/bin/env python3
"""The FTS5 side of a similar-runs query: what to MATCH and the bm25 ranking.

A target's document (:class:`~vmn_exp.core.similar_doc.Doc`) becomes one
``MATCH`` expression: per column at most :data:`MAX_TERMS` of its terms, the
rarest first (document frequencies from ``similar_vocab``), each a quoted
string — never query syntax, whatever the text holds. Text words are
stemmed by FTS5 itself (a temp FTS table and its ``instance`` vocabulary) to
look their frequencies up. Rarity also bounds the work: past the
:data:`MIN_TERMS` rarest terms, terms are taken while their documents add up
to at most :data:`POSTINGS_PER_DOC` times the documents filed (at least
:data:`POSTINGS_BUDGET`): bm25 is computed per matching document and phrase,
so a common term costs the most and adds the least. The work then grows
with the app, never faster. :func:`rank` pages the matches by
``bm25`` under per-column weights; :func:`deadline` interrupts any of it.
"""
import contextlib
import re
import sqlite3
import time

from vmn_exp.core import similar_fts
from vmn_exp.core.similar_doc import COLUMNS, STRUCTURED, word
from vmn_exp.core.similar_items import utf8_safe

MAX_TERMS = 64
MIN_TERMS = 8
POSTINGS_BUDGET = 40_000
POSTINGS_PER_DOC = 1
PROGRESS_OPS = 2000  # SQLite VM steps between two looks at a deadline
_WORD = re.compile(r"[^\W_]+")
_clock = time.monotonic


class SimilarDeadlineExceeded(Exception):
    """A similar-runs search ran past its deadline."""


@contextlib.contextmanager
def deadline(conn, at):
    """Interrupt *conn*'s statements once :func:`time.monotonic` passes *at*
    (none when None), raising :class:`SimilarDeadlineExceeded`."""
    if at is None:
        yield
        return
    conn.set_progress_handler(lambda: 1 if _clock() >= at else 0, PROGRESS_OPS)
    try:
        if _clock() >= at:
            raise SimilarDeadlineExceeded
        yield
    except sqlite3.OperationalError as exc:
        if "interrupt" in str(exc):
            raise SimilarDeadlineExceeded from None
        raise
    finally:
        conn.set_progress_handler(None, 0)


def words(text):
    """The distinct lowercased words of *text*, in order."""
    if not isinstance(text, str):
        return []
    found = _WORD.findall(utf8_safe(text).lower())
    return list(dict.fromkeys(found))


def stems(conn, wanted):
    """``{word: [its FTS5 stems]}`` (``porter unicode61``) of *wanted* words."""
    if not wanted:
        return {}
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.similar_q"
                 " USING fts5(w, tokenize = 'porter unicode61')")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.similar_qi"
                 " USING fts5vocab(temp, similar_q, 'instance')")
    conn.execute("DELETE FROM temp.similar_q")
    conn.executemany("INSERT INTO temp.similar_q (rowid, w) VALUES (?, ?)",
                     list(enumerate(wanted, 1)))
    out = {}
    for doc, term in conn.execute("SELECT doc, term FROM temp.similar_qi ORDER BY doc, offset"):
        out.setdefault(wanted[doc - 1], []).append(term)
    conn.execute("DELETE FROM temp.similar_q")
    return out


def quoted(text):
    return '"' + text.replace('"', '""') + '"'


class Match:
    """What a target asks: *terms* ``[(column, term, df, query string)]``,
    rarest first, *stems* ``{word: stems}`` of its text and *df* ``{(column,
    term): documents}`` of every term of it any document holds."""

    def __init__(self, terms, stems_of, df=None):
        self.terms, self.stems, self.df = terms, stems_of, df or {}

    def expression(self):
        """The MATCH expression; None when nothing can match."""
        if not self.terms:
            return None
        return " OR ".join(f"{column} : {query}" for column, _, _, query in self.terms)


def _candidates(conn, doc, columns):
    """``{column: [(term, query string)]}`` of *doc* in *columns*, and the stems."""
    found, stems_of = {}, {}
    if "text" in columns:
        stems_of = stems(conn, words(doc.text))
        found["text"] = list({stem: quoted(w) for w, ss in stems_of.items()
                              for stem in ss}.items())
    for column in STRUCTURED:
        if column in columns and doc.cols.get(column):
            found[column] = [(word(t), quoted(word(t))) for t in doc.cols[column]]
    return found, stems_of


def build_match(conn, doc, columns):
    """The :class:`Match` of target *doc* over *columns* (the weighted ones)."""
    found, stems_of = _candidates(conn, doc, columns)
    df = similar_fts.document_frequencies(
        conn, {column: [term for term, _ in terms] for column, terms in found.items()})
    terms = []
    for column, pairs in found.items():
        known = [(column, term, df[(column, term)], query) for term, query in pairs
                 if df.get((column, term))]
        known.sort(key=lambda t: (t[2], t[1]))
        terms += known[:MAX_TERMS]
    terms.sort(key=lambda t: (t[2], t[0], t[1]))
    (filed,) = conn.execute("SELECT COALESCE(MAX(id), 0) FROM similar_doc").fetchone()
    budget = max(POSTINGS_BUDGET, POSTINGS_PER_DOC * filed)
    kept, postings = [], 0
    for term in terms:
        postings += term[2]
        if len(kept) >= MIN_TERMS and postings > budget:
            break
        kept.append(term)
    return Match(kept, stems_of, df)


def rank(conn, app, expression, weights, offset, limit):
    """``(page, more)``: *app*'s documents among the *limit* best matches of
    *expression* from *offset* on — ``[(verstr, score)]``, score = -bm25 under
    *weights* ``{column: weight}``, above 0 — and whether the ranking goes on.

    The ranking runs over the whole file and reads no document: filtering on
    the unindexed ``app`` would read every match's row (twice the time), so a
    page's other apps are dropped once ranked."""
    w = ", ".join(repr(float(weights.get(c, 0.0))) for c in COLUMNS)
    ranked = conn.execute(
        f"SELECT rowid, bm25(similar_fts, 0.0, 0.0, {w}) AS s FROM similar_fts"
        " WHERE similar_fts MATCH ? ORDER BY s, rowid LIMIT ? OFFSET ?",
        (expression, limit, offset)).fetchall()
    owners = {}
    for chunk in similar_fts.chunks(rowid for rowid, _ in ranked):
        owners.update((doc_id, (owner, verstr)) for doc_id, owner, verstr in conn.execute(
            f"SELECT id, app, verstr FROM similar_doc WHERE id IN ({similar_fts.marks(chunk)})",
            chunk))
    page = [(owners[rowid][1], -score) for rowid, score in ranked
            if score < 0 and owners.get(rowid, (None,))[0] == app]
    return page, len(ranked) == limit
