#!/usr/bin/env python3
"""The inverted index similar runs draws candidates from.

Every run of a snapshot is filed under the tokens of its profile
(:func:`~vmn_exp.core.similar_profile.profile_tokens`: changed files and
symbols, input digests and dataset names, param keys, script, objective
metrics, base commit, and the words of its text document). A query's
candidates are the runs sharing at least one token with it, taken from the
rarest token first up to :data:`CANDIDATE_CAP` — no pairwise work over the
app, and a common token (``pkey:lr``) cannot crowd out a rare one.

An index is built once per snapshot object and kept while the snapshot
lives (snapshots are immutable; the experiment index swaps in a new one per
generation). The snapshot is duck-typed: ``.rows``, and when it has them
``.features_of``/``.intent_of``/``.hypothesis_of(verstr)``, ``.run_states``
and ``.create_notes``. Pure: no storage.
"""
import threading
import weakref

from vmn_exp.core.similar_profile import build_profile, profile_tokens
from vmn_exp.core.similar_text import Bm25

CANDIDATE_CAP = 5000

_CACHE = weakref.WeakKeyDictionary()
_CACHE_LOCK = threading.Lock()


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


class SimilarIndex:
    def __init__(self, snapshot):
        features_of, intent_of, hypothesis_of = side_tables(snapshot)
        notes = getattr(snapshot, "create_notes", None) or {}
        self._rows, self._profiles, self._postings = {}, {}, {}
        self.parents = set()
        docs = length = 0
        for row in snapshot.rows:
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

    def _document_frequency(self, term):
        return len(self._postings.get("w:" + term, ()))

    def row(self, verstr):
        """The snapshot's row of *verstr* (shared: copy before changing), or None."""
        return self._rows.get(verstr)

    def profile(self, verstr):
        return self._profiles.get(verstr)

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


def index_for(snapshot):
    """The :class:`SimilarIndex` of *snapshot*, built on first use."""
    try:
        with _CACHE_LOCK:
            found = _CACHE.get(snapshot)
    except TypeError:  # neither hashable nor weak-referenceable: no caching
        return SimilarIndex(snapshot)
    if found is None:
        found = SimilarIndex(snapshot)
        with _CACHE_LOCK:
            _CACHE[snapshot] = found
    return found
