#!/usr/bin/env python3
"""A search index over every run of an app (plan 23 S8), once per index
snapshot and moved on from the app's previous one.

Each run's searchable text — name, verstr, note, tags (keys and values),
param values, command, branch, author, error summary and intent text — is
lowercased and packed, per field, into one string per chunk of storage
slots: ``SEP`` before every run's value, a run's several strings joined by
``"\\x00"`` and every control character in them turned into ``"\\x00"``. A
needle (lowercased, no control character) is then found with ``str.find``
at C speed, never across two strings, and the separators counted up to a
hit name its run — so the index costs about the text itself, with no
per-run objects (where trigram postings would cost several times that).

A new generation is moved on like the facets
(:mod:`~vmn_exp.ui.leaderboard_facets`): the slots whose row object changed
(found by identity), whose run state's command or error summary changed, or
whose intent changed get their text again, and only the chunks whose text
differs are rebuilt; the rest are shared with the previous index.
"""
import threading
from itertools import compress
from operator import is_not

from vmn_exp.core.run_error import state_error_summary
from vmn_exp.ui.leaderboard_delta import changed_slots, delta_limit
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.search_rank import ranked

FIELDS = ("name", "verstr", "note", "tags", "params", "command", "branch", "author",
          "error_summary", "intent")
FIELD_AT = {field: i for i, field in enumerate(FIELDS)}
CHUNK = 1024
SEP = "\x01"
_JOIN = "\x00"
_CONTROL = {c: 0 for c in range(1, 32)}


def _strings(value):
    """The strings ``~`` matches in *value* (dict keys too, numbers as text)."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)] + [str(k) for k in value]
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return [str(value)]


def _text(strings):
    return _JOIN.join(s.lower() for s in strings).translate(_CONTROL)


def _state_texts(state):
    """``(command, error summary)`` texts of a run state."""
    if not state:
        return "", ""
    return _text(_strings(state.get("command"))), _text(_strings(state_error_summary(state)))


def _doc(snapshot, row):
    """*row*'s text per field, in :data:`FIELDS` order."""
    command, error = _state_texts(snapshot.run_states.get(row["verstr"]))
    intent = snapshot.intents.get(row["verstr"]) or {}
    params = row.get("params") or {}
    return (
        _text(_strings(row.get("name"))), _text([row["verstr"]]),
        _text(_strings(row.get("note"))), _text(_strings(row.get("tags"))),
        _text([s for v in params.values() for s in _strings(v)]), command,
        _text(_strings(row.get("branch"))), _text(_strings(row.get("author"))), error,
        _text(_strings(intent.get("text") if isinstance(intent, dict) else None)),
    )


def needle_of(text):
    """*text* as a needle, or None when the index cannot look for it."""
    needle = (text or "").lower()
    if not needle or needle.translate(_CONTROL) != needle:
        return None
    return needle


def scan(text, needle):
    """The indexes of the values of a field *text* holding *needle*, each once,
    in order (*needle* may start with ``SEP``: a value prefix)."""
    k, at = -1, 0
    p = text.find(needle)
    while p >= 0:
        k += text.count(SEP, at, p + 1)
        yield k
        at = text.find(SEP, p + 1)
        if at < 0:
            return
        p = text.find(needle, at)


def rscan(text, needle, size):
    """:func:`scan`'s indexes, last first (*size* values in *text*)."""
    after, cursor, end = 0, len(text), len(text)
    while end > 0:
        p = text.rfind(needle, 0, end)
        if p < 0:
            return
        after += text.count(SEP, p + 1, cursor)
        cursor = p + 1
        yield size - 1 - after
        end = text.rfind(SEP, 0, p + 1)


class Chunk:
    """The packed field texts of *size* consecutive slots."""

    __slots__ = ("size", "texts")

    def __init__(self, texts, size):
        self.texts = tuple(texts)
        self.size = size

    @classmethod
    def of(cls, docs):
        return cls((SEP + SEP.join(values) for values in zip(*docs)), len(docs))

    def replaced(self, changes, size):
        """This chunk with *size* values, *changes* ``{offset: (doc, old doc
        or None)}`` put in; only the fields a change differs in are rebuilt."""
        texts = list(self.texts)
        for f, text in enumerate(texts):
            if size == self.size and all(
                    old is not None and doc[f] == old[f] for doc, old in changes.values()):
                continue
            values = text[1:].split(SEP)[:size]
            values += [""] * (size - len(values))
            for k, (doc, _) in changes.items():
                values[k] = doc[f]
            texts[f] = SEP + SEP.join(values)
        return Chunk(texts, size)


class SearchIndex:
    fields, sep, needle_of = FIELDS, SEP, staticmethod(needle_of)

    def __init__(self, snapshot, chunks, chunk):
        self.snapshot = snapshot
        self.chunks = chunks
        self.chunk = chunk

    @classmethod
    def build(cls, snapshot, chunk=CHUNK):
        """From scratch: O(N)."""
        docs = [_doc(snapshot, row) for row in snapshot.rows]
        chunks = [Chunk.of(docs[at:at + chunk]) for at in range(0, len(docs), chunk)]
        return cls(snapshot, chunks, chunk)

    def moved(self, snapshot):
        """This index for *snapshot*: the changed slots' chunks rebuilt, the
        others shared; built from scratch when much changed."""
        rows, old = snapshot.rows, self.snapshot.rows
        slots = changed_slots(rows, old, delta_limit(rows))
        restated = slots is not None and self._restated(snapshot)
        if restated is None or slots is None:
            return SearchIndex.build(snapshot, self.chunk)
        fresh = {}
        for i in set(slots) | restated:
            doc, was = _doc(snapshot, rows[i]), i < len(old) and _doc(self.snapshot, old[i])
            if doc != was:
                fresh[i] = (doc, was or None)
        return SearchIndex(snapshot, self._chunks_with(fresh, len(rows)), self.chunk)

    def _restated(self, snapshot):
        """Slots of unchanged rows whose state texts or intent changed; None
        when a verstr repeats (the slots cannot be told by verstr)."""
        new, old = snapshot, self.snapshot
        if len(new.edges) != len(new.rows):
            return None
        verstrs = list(new.edges)[: len(old.rows)]
        states, was = new.run_states, old.run_states
        moved = compress(range(len(verstrs)),
                         map(is_not, map(states.get, verstrs), map(was.get, verstrs)))
        out = {i for i in moved
               if _state_texts(states.get(verstrs[i])) != _state_texts(was.get(verstrs[i]))}
        for verstr in new.intents.keys() | old.intents.keys():
            if new.intents.get(verstr) is not old.intents.get(verstr):
                out.add(_slot_of(new, verstr))
        out.discard(None)
        return out

    def _chunks_with(self, fresh, n):
        """The chunks of *n* slots, *fresh* ``{slot: (doc, old doc or None)}``
        put in."""
        size = self.chunk
        chunks = list(self.chunks[: -(-n // size)])
        changes = {}
        for i, change in fresh.items():
            if i // size < len(chunks):
                changes.setdefault(i // size, {})[i % size] = change
        if chunks and chunks[-1].size != min(size, n - (len(chunks) - 1) * size):
            changes.setdefault(len(chunks) - 1, {})  # the last kept chunk shrank or grew
        for c, change in changes.items():
            chunks[c] = chunks[c].replaced(change, min(size, n - c * size))
        for start in range(len(chunks) * size, n, size):
            chunks.append(Chunk.of([fresh[i][0] for i in range(start, min(n, start + size))]))
        return chunks

    def slots(self, needle, fields=FIELDS):
        """The set of slots with a *fields* text holding *needle* (lowercased)."""
        at = [FIELD_AT[f] for f in fields]
        out = set()
        for c, chunk in enumerate(self.chunks):
            base = c * self.chunk
            for f in at:
                out.update(base + k for k in scan(chunk.texts[f], needle))
        return out

    def find(self, text, fields=FIELDS):
        """The sorted slots whose *fields* match ``~ text``; None when *text*
        is no needle (empty, or with a control character)."""
        needle = needle_of(text)
        return None if needle is None else sorted(self.slots(needle, fields))

    def newest(self, needle, field):
        """Slots of *field* texts holding *needle*, newest first, lazily."""
        f = FIELD_AT[field]
        for c in range(len(self.chunks) - 1, -1, -1):
            chunk = self.chunks[c]
            for k in rscan(chunk.texts[f], needle, chunk.size):
                yield c * self.chunk + k

    def ranked(self, text, limit, archived=False):
        """``[(slot, matched field)]``, see :func:`~vmn_exp.ui.search_rank.ranked`."""
        return ranked(self, text, limit, archived)

    def nbytes(self):
        """The packed texts' size in bytes."""
        return sum(text.__sizeof__() for chunk in self.chunks for text in chunk.texts)


def _slot_of(snapshot, verstr):
    """*verstr*'s storage slot (its ``idx`` - 1 when that holds), or None."""
    row, rows = snapshot.row(verstr), snapshot.rows
    if row is None:
        return None
    i = row["idx"] - 1 if isinstance(row.get("idx"), int) else -1
    if 0 <= i < len(rows) and rows[i] is row:
        return i
    return next((i for i, other in enumerate(rows) if other is row), None)


class SearchIndexes:
    """A :class:`SearchIndex` per snapshot, each moved on from the app's latest."""

    def __init__(self, size=4, chunk=CHUNK):
        self.chunk = chunk
        self._indexes = LRU(size)
        self._latest = {}  # app -> SearchIndex
        self._lock = threading.Lock()

    def get(self, snapshot):
        return self._indexes.per_snapshot(snapshot, lambda: self._moved(snapshot))

    def _moved(self, snapshot):
        with self._lock:
            prev = self._latest.get(snapshot.app_name)
        index = prev.moved(snapshot) if prev else SearchIndex.build(snapshot, self.chunk)
        with self._lock:
            self._latest[snapshot.app_name] = index
        return index
