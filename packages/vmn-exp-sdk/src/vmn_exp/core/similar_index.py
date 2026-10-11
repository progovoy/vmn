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
SDK runs they open are one tree under the sweep's outer run.

An index is built once per snapshot object and kept while the snapshot
lives (snapshots are immutable; the experiment index swaps in a new one per
generation). The snapshot is duck-typed: ``.rows``, and when it has them
``.features_of``/``.intent_of``/``.hypothesis_of(verstr)``, ``.run_states``
and ``.create_notes``. Pure: no storage.

A search may carry a *deadline* (a :func:`time.monotonic` value): the build
and the scoring look at the clock every :data:`DEADLINE_CHECK_EVERY` rows or
candidates and raise :class:`SimilarDeadlineExceeded` past it — an
interrupted build caches nothing.
"""
import threading
import time
import weakref

from vmn_exp.core.similar_profile import build_profile, profile_tokens
from vmn_exp.core.similar_text import Bm25

CANDIDATE_CAP = 5000
# Rows indexed or candidates scored between two looks at a deadline: a look
# is a clock read, and a search overruns its deadline by at most this much work.
DEADLINE_CHECK_EVERY = 32
_clock = time.monotonic

_CACHE = weakref.WeakKeyDictionary()
_CACHE_LOCK = threading.Lock()


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


class SimilarIndex:
    def __init__(self, snapshot, deadline=None):
        features_of, intent_of, hypothesis_of = side_tables(snapshot)
        notes = getattr(snapshot, "create_notes", None) or {}
        self._rows, self._profiles, self._postings = {}, {}, {}
        self.parents = set()
        docs = length = 0
        for done, row in enumerate(snapshot.rows):
            check_deadline(deadline, done)
            verstr = row["verstr"]
            profile = build_profile(
                row, features_of(verstr), intent_of(verstr), hypothesis_of(verstr),
                command=run_command(snapshot, row), create_note=notes.get(verstr),
            )
            self._rows[verstr], self._profiles[verstr] = row, profile
            for token in profile_tokens(profile):
                self._postings.setdefault(token, []).append(verstr)
            if row.get("parent"):
                self.parents.add(row["parent"])
            docs += bool(profile.length)
            length += profile.length
        self.bm25 = Bm25(docs, length / docs if docs else 1.0, self._document_frequency)
        self._roots = _tree_roots(self._rows)

    def _document_frequency(self, term):
        return len(self._postings.get("w:" + term, ()))

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
        return tuple(self._postings.get(token, ()))

    def candidates(self, tokens, cap=CANDIDATE_CAP, keep=None):
        """Verstrs sharing a token with *tokens*: the rarest token's runs
        first (newest first within a token), at most *cap*; *keep(verstr)*
        rejects runs before they take a place."""
        known = sorted((t for t in set(tokens) if t in self._postings),
                       key=lambda t: (len(self._postings[t]), t))
        chosen, rejected = {}, set()
        for token in known:
            for verstr in reversed(self._postings[token]):
                if verstr in chosen or verstr in rejected:
                    continue
                if keep is not None and not keep(verstr):
                    rejected.add(verstr)
                    continue
                chosen[verstr] = None
                if len(chosen) >= cap:
                    return list(chosen)
        return list(chosen)


def index_for(snapshot, deadline=None):
    """The :class:`SimilarIndex` of *snapshot*, built on first use (by
    *deadline*, when given)."""
    try:
        with _CACHE_LOCK:
            found = _CACHE.get(snapshot)
    except TypeError:  # neither hashable nor weak-referenceable: no caching
        return SimilarIndex(snapshot, deadline)
    if found is None:
        found = SimilarIndex(snapshot, deadline)
        with _CACHE_LOCK:
            _CACHE[snapshot] = found
    return found
