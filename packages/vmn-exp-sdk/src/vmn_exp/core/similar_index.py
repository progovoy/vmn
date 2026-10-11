#!/usr/bin/env python3
"""The inverted index similar runs draws candidates from.

Every run of a snapshot is filed under the tokens of its profile
(:func:`~vmn_exp.core.similar_profile.profile_tokens`: changed files and
symbols, input digests and dataset names, param keys, script, objective
metrics, base commit, and the words of its text document). A query's
candidates are the runs sharing at least one token with it, taken from the
rarest token first up to :data:`CANDIDATE_CAP` — no pairwise work over the
app, and a common token (``pkey:lr``) cannot crowd out a rare one. It also
knows each run's tree (:meth:`SimilarIndex.root`): a sweep's trials and the
SDK runs they open are one tree under the sweep's outer run. A *structured*
False index files the words only: all a text search needs.

An index is built once per snapshot object and kept while the snapshot
lives (snapshots are immutable; the experiment index swaps in a new one per
generation), by one caller at a time (:mod:`vmn_exp.core.similar_cache`).
:func:`build_index` builds it from the index of an earlier snapshot of the
same runs: a run whose row and side values are the same objects (the
experiment index reuses them while a record is unchanged) and whose command
and create note are equal keeps its profile, the postings are patched for
the runs that changed (:mod:`vmn_exp.core.similar_postings`), and a snapshot
changing nothing the index reads — a heartbeat moves run states only — gets
the earlier index itself. The snapshot is duck-typed: ``.rows``, and when it
has them ``.features_of``/``.intent_of``/``.hypothesis_of(verstr)``,
``.run_states`` and ``.create_notes``. Pure: no storage.

A search may carry a *deadline* (a :func:`time.monotonic` value): the build
and the scoring look at the clock every :data:`DEADLINE_CHECK_EVERY` rows or
candidates and raise :class:`SimilarDeadlineExceeded` past it — an
interrupted build caches nothing.
"""
import time
from collections import namedtuple

from vmn_exp.core.similar_postings import filed, kept_order, refiled, worth_patching
from vmn_exp.core.similar_profile import (
    WORD_PREFIX,
    build_profile,
    structured_tokens,
    word_tokens,
)
from vmn_exp.core.similar_text import Bm25

CANDIDATE_CAP = 5000
# Rows indexed or candidates scored between two looks at a deadline: a look
# is a clock read, and a search overruns its deadline by at most this much work.
DEADLINE_CHECK_EVERY = 32
_clock = time.monotonic


class SimilarDeadlineExceeded(Exception):
    """A similar-runs search ran past its deadline."""


def check_deadline(deadline, done):
    """Raise :class:`SimilarDeadlineExceeded` when *deadline* has passed —
    looked at once every :data:`DEADLINE_CHECK_EVERY` units of work, *done*
    counting them; never without a *deadline*."""
    if deadline is not None and done % DEADLINE_CHECK_EVERY == 0 and _clock() >= deadline:
        raise SimilarDeadlineExceeded


def _none(_verstr):
    return None


def side_tables(snapshot):
    """``(features_of, intent_of, hypothesis_of)`` of *snapshot*; a missing
    accessor reads as None for every run."""
    return tuple(getattr(snapshot, name, None) or _none
                 for name in ("features_of", "intent_of", "hypothesis_of"))


def run_command(snapshot, row):
    """The argv a run ran: its row's ``command``, else its run state's."""
    states = getattr(snapshot, "run_states", None) or {}
    return row.get("command") or (states.get(row["verstr"]) or {}).get("command")


def run_facts(snapshot):
    """``facts(row)``: ``(features, intent, hypothesis, command, create
    note)`` of a run of *snapshot* (:func:`side_tables`,
    :func:`run_command`), its accessors looked up once."""
    features_of, intent_of, hypothesis_of = side_tables(snapshot)
    notes = getattr(snapshot, "create_notes", None) or {}

    def facts(row):
        verstr = row["verstr"]
        return (features_of(verstr), intent_of(verstr), hypothesis_of(verstr),
                run_command(snapshot, row), notes.get(verstr))
    return facts


def _tree_roots(rows):
    """verstr -> the top of its ``parent`` chain in *rows* (verstr -> row):
    the first ancestor without a parent, else an ancestor's parent missing
    from *rows* (it still ties its runs together), else where a cycle closes."""
    roots = {}
    for start in rows:
        if start in roots:
            continue
        chain, node = [], start
        while True:
            chain.append(node)
            parent = rows[node].get("parent")
            if not parent:
                root = node
            elif parent in roots:
                root = roots[parent]
            elif parent not in rows or parent in chain:
                root = parent
            else:
                node = parent
                continue
            break
        roots.update(dict.fromkeys(chain, root))
    return roots


# A scan of a snapshot: verstr -> row / facts (features, intent, hypothesis,
# command, create note) / profile, in snapshot order; the verstrs whose
# profile was built anew; whether every row is the earlier index's object.
_Scan = namedtuple("_Scan", "rows facts profiles rebuilt same_rows")


def _same_facts(old, new):
    return (old[0] is new[0] and old[1] is new[1]
            and old[2] == new[2] and old[3] == new[3] and old[4] == new[4])


_MISSING = object()


def _same_row(old, new):
    """Whether *new* is *old*, or a copy of it renumbered: the experiment
    index re-numbers (``idx``) the rows after a deleted one, sharing every
    other value."""
    if old is new:
        return True
    if old is None or len(old) != len(new):
        return False
    return all(key == "idx" or new.get(key, _MISSING) is value for key, value in old.items())


def _scan(snapshot, previous, deadline):
    """Every run's row, facts and profile — *previous*'s profile when its
    row is the same object (or a renumbered copy) and its facts the same
    (side values by identity)."""
    facts_of = run_facts(snapshot)
    old_rows, old_facts, old_profiles = (
        (previous._rows, previous._facts, previous._profiles) if previous is not None
        else ({}, {}, {}))
    rows, facts, profiles, rebuilt, same_rows = {}, {}, {}, {}, True
    for done, row in enumerate(snapshot.rows):
        check_deadline(deadline, done)
        verstr, mine = row["verstr"], facts_of(row)
        old = old_rows.get(verstr)
        same_rows = same_rows and old is row
        if _same_row(old, row) and _same_facts(old_facts[verstr], mine):
            profile = old_profiles[verstr]
        else:
            profile = build_profile(row, mine[0], mine[1], mine[2],
                                    command=mine[3], create_note=mine[4])
            rebuilt[verstr] = None
        rows[verstr], facts[verstr], profiles[verstr] = row, mine, profile
    return _Scan(rows, facts, profiles, list(rebuilt), same_rows)


def _changes(previous, scan):
    """``(verstr, profile before | None, profile now | None)`` of the runs
    rebuilt, new or gone since *previous*."""
    old = previous._profiles
    changes = [(v, old.get(v), scan.profiles[v]) for v in scan.rebuilt]
    changes += [(v, old[v], None) for v in old.keys() - scan.profiles.keys()]
    return changes


class SimilarIndex:
    """A snapshot's inverted index (see the module docstring), built from
    *previous* (an index of an earlier snapshot of the same runs) when given."""

    def __init__(self, snapshot, deadline=None, previous=None, structured=True):
        self._assemble(_scan(snapshot, previous, deadline), previous, structured, deadline)

    @classmethod
    def _of_scan(cls, scan, previous, structured, deadline):
        index = cls.__new__(cls)
        index._assemble(scan, previous, structured, deadline)
        return index

    def _assemble(self, scan, previous, structured, deadline):
        self._rows, self._facts, self._profiles = scan.rows, scan.facts, scan.profiles
        self.structured = bool(structured)
        self._pos = {verstr: at for at, verstr in enumerate(self._rows)}
        changes = _changes(previous, scan) if previous is not None else None
        patch = (changes is not None and worth_patching(len(changes), len(self._rows))
                 and kept_order(previous._pos, self._rows))

        def postings(old, tokens_of):
            if patch and old is not None:
                return refiled(old, self._pos, changes, tokens_of)
            return filed(self._profiles, tokens_of,
                         None if deadline is None else lambda done: check_deadline(deadline, done))

        self._words = postings(previous and previous._words, word_tokens)
        self._structured = (postings(previous and previous._structured, structured_tokens)
                            if structured else None)
        self._link(previous if patch else None, changes)
        docs = sum(1 for p in self._profiles.values() if p.length)
        length = sum(p.length for p in self._profiles.values())
        self.bm25 = Bm25(docs, length / docs if docs else 1.0, self._document_frequency)

    def _link(self, previous, changes):
        """Parents and tree roots: *previous*'s (of runs in the same order)
        while no run came, went or changed its parent."""
        if previous is not None and all(
                before is not None and now is not None
                and previous._rows[v].get("parent") == self._rows[v].get("parent")
                for v, before, now in changes):
            self.parents, self._roots = previous.parents, previous._roots
            return
        self.parents = {row["parent"] for row in self._rows.values() if row.get("parent")}
        self._roots = _tree_roots(self._rows)

    def _table(self, token):
        """The postings *token* is filed in (none for a structured token of a
        words-only index)."""
        if token.startswith(WORD_PREFIX):
            return self._words
        return self._structured or {}

    def _document_frequency(self, term):
        return len(self._words.get(WORD_PREFIX + term, ()))

    def unchanged_by(self, scan):
        """Whether *scan* (of a later snapshot, from this index) changed
        nothing: no profile, no row object (rows are told apart by identity:
        a search's filter does), no order."""
        return scan.same_rows and not scan.rebuilt and list(scan.rows) == list(self._rows)

    def row(self, verstr):
        """The snapshot's row of *verstr* (shared: copy before changing), or None."""
        return self._rows.get(verstr)

    def profile(self, verstr):
        return self._profiles.get(verstr)

    def root(self, row):
        """The verstr *row*'s tree is filed under (see :func:`_tree_roots`);
        a run with neither parent nor children is its own. *row* need not
        be in the snapshot."""
        verstr, parent = row.get("verstr"), row.get("parent")
        if verstr in self._roots:
            return self._roots[verstr]
        return self._roots.get(parent, parent) if parent else verstr

    def in_tree(self, row):
        """Whether *row* has a parent or children."""
        return bool(row.get("parent")) or row.get("verstr") in self.parents

    def posting(self, token):
        """The verstrs filed under *token*, in snapshot order."""
        return tuple(self._table(token).get(token, ()))

    def candidates(self, tokens, cap=CANDIDATE_CAP, keep=None):
        """Verstrs sharing a token with *tokens*: the rarest token's runs
        first (newest first within a token), at most *cap*; *keep(verstr)*
        rejects runs before they take a place."""
        lists = {}
        for token in set(tokens):
            found = self._table(token).get(token)
            if found:
                lists[token] = found
        chosen, rejected = {}, set()
        for token in sorted(lists, key=lambda t: (len(lists[t]), t)):
            for verstr in reversed(lists[token]):
                if verstr in chosen or verstr in rejected:
                    continue
                if keep is not None and not keep(verstr):
                    rejected.add(verstr)
                    continue
                chosen[verstr] = None
                if len(chosen) >= cap:
                    return list(chosen)
        return list(chosen)


def build_index(snapshot, deadline=None, previous=None, structured=True):
    """The :class:`SimilarIndex` of *snapshot* — from *previous*, an index
    of an earlier snapshot of the same runs, when given: *previous* itself
    when *snapshot* changes nothing it reads (and it files what is asked)."""
    scan = _scan(snapshot, previous, deadline)
    if (previous is not None and previous.unchanged_by(scan)
            and (previous.structured or not structured)):
        return previous
    return SimilarIndex._of_scan(scan, previous, structured, deadline)


def index_for(snapshot, deadline=None, structured=True):
    """The :class:`SimilarIndex` of *snapshot*, built on first use (by
    *deadline*, when given) by one caller at a time; *structured* False
    settles for a words-only index (see :func:`vmn_exp.core.similar_cache.index_for`)."""
    from vmn_exp.core.similar_cache import index_for as cached

    return cached(snapshot, deadline, structured)
