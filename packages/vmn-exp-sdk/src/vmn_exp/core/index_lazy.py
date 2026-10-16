#!/usr/bin/env python3
"""A persisted record read on demand (plan 25 §2): what a warm restart puts
in an :class:`~vmn_exp.core.index.ExperimentIndex` instead of decoding every
record.

A :class:`LazyRecord` starts as its run state alone (``rs_sig``/
``run_state``, which every snapshot needs). Its head — the signatures a
refresh compares — is read the first time anything else is touched, in the
same query as its fold, which is decoded only when a refresh reads or
refolds it. Both are read at the generation the snapshot's rows were read at;
when another process has rewritten the record since, it reads as a new,
empty record, so the next refresh loads it from storage again.

To everything else it is the plain dict it stands for: every access that
could see a missing key loads what it needs first, and it pickles as a plain
dict.
"""
import json

STATE_KEYS = ("rs_sig", "run_state")
_PENDING = object()  # nothing read yet; a str: the head read, the fold not decoded
_DECODED = object()  # the run state is in the dict; else _PENDING, or its JSON (None: none)
FOLD = "fold"


def decode_fold(key, data):
    """The fold of record *key* from its stored JSON."""
    return json.loads(data)


def has_meta(record):
    """Whether *record* has metadata (is a run); a :class:`LazyRecord`
    answers without reading its head."""
    if isinstance(record, LazyRecord):
        return record.has_meta()
    return record["meta"] is not None


def _blank():
    # Imported here: index_record imports the sweep, which imports this module.
    from vmn_exp.core.index_record import new_record

    return {k: v for k, v in new_record().items() if k not in STATE_KEYS}


class LazyRecord(dict):
    __slots__ = ("_fetch", "_key", "_raw", "_run", "_state")

    def __init__(self, key, state, fetch, run):
        """*state*: the record's run state fields, or None to read them with
        its head; *fetch(key)*: its stored ``(head JSON, fold JSON, run state
        JSON or None)``, or None when no longer stored as read; *run*:
        whether it was stored as a run (with metadata)."""
        super().__init__(state or ())
        self._key, self._fetch, self._raw, self._run = key, fetch, _PENDING, run
        self._state = _DECODED if state is not None else _PENDING

    def _decode_state(self):
        if self._state is _DECODED:
            return
        self._head()
        raw, self._state = self._state, _DECODED
        dict.update(self, dict.fromkeys(STATE_KEYS))
        if isinstance(raw, str):
            dict.update(self, json.loads(raw))

    def has_meta(self):
        """Whether the record has metadata, without reading its head."""
        if self._raw is _PENDING:
            return self._run
        return dict.get(self, "meta") is not None

    def _head(self):
        if self._raw is not _PENDING:
            return
        parts = self._fetch(self._key)
        if parts is None:
            self._raw = None
            if self._state is _PENDING:
                self._state = None
            dict.update(self, _blank())
            return
        head, data, state = parts
        dict.update(self, json.loads(head))
        self._raw = data
        if self._state is _PENDING:
            self._state = state

    def _all(self):
        self._decode_state()
        self._head()
        if isinstance(self._raw, str):
            raw, self._raw = self._raw, None
            dict.__setitem__(self, FOLD, decode_fold(self._key, raw))

    def _load(self, key):
        self._decode_state()
        if key == FOLD:
            self._all()
        elif key not in STATE_KEYS:
            self._head()

    def __missing__(self, key):
        self._load(key)
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        raise KeyError(key)

    def get(self, key, default=None):
        self._load(key)
        return dict.get(self, key, default)

    def setdefault(self, key, default=None):
        self._load(key)
        return dict.setdefault(self, key, default)

    def __contains__(self, key):
        if key == FOLD and isinstance(self._raw, str):
            return True
        self._load(key)
        return dict.__contains__(self, key)

    def __setitem__(self, key, value):
        if key == FOLD:
            self._head()
            self._raw = None  # replaced: the stored fold is never decoded
        else:
            self._load(key)
        dict.__setitem__(self, key, value)

    def pop(self, key, *default):
        self._load(key)
        return dict.pop(self, key, *default)


def _loading_all(name):
    method = getattr(dict, name)

    def loaded(self, *args, **kwargs):
        self._all()
        return method(self, *args, **kwargs)

    loaded.__name__ = name
    return loaded


for _name in ("__iter__", "__len__", "__eq__", "__ne__", "__repr__", "__delitem__",
              "keys", "items", "values", "copy", "update", "popitem"):
    setattr(LazyRecord, _name, _loading_all(_name))
LazyRecord.__hash__ = None


def _reduce(self, protocol=None):
    self._all()
    return dict, (dict(dict.items(self)),)


LazyRecord.__reduce_ex__ = _reduce
LazyRecord.__reduce__ = _reduce
