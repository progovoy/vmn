#!/usr/bin/env python3
"""A storage's listings as *changes* since the previous listing, for
:mod:`experiment_index_sweep`.

At 100k records the listings themselves are cheap next to what a caller does
with them per record, so this reports only what moved: the names whose
signature changed (or appeared) and the names gone since the previous
``name_changes``, and the records whose files differ from the last time a
full or sliced listing (``full_changes``/``slice_changes``) saw them. The same class runs in the index's process or, for a plain
local store, in its I/O helper process (:mod:`experiment_index_io_process`),
where the baselines live next to the listings and only changes cross the pipe.

A caller that failed to apply a change calls :meth:`reset`: the next listings
then report everything again.

The baselines outlive the process (:mod:`~vmn_exp.core.index_baseline`):
:meth:`ListingWatch.baseline` hands them out with the keys that moved since
the last call, :meth:`ListingWatch.restore` takes them back. Fingerprints are
stable across processes for that (``hash()`` of a string is not).
"""
import hashlib

from vmn_exp.core.index_journal_moves import journal_moves

METADATA_FILE = "metadata.yml"


def as_sigs(names):
    """``{name: sig}`` from a backend's names listing (a plain set of names:
    all-None sigs); None stays None."""
    if names is None or isinstance(names, dict):
        return names
    return dict.fromkeys(names)


def _fingerprint(files):
    """A cheap equality stand-in for a record's ``{name: signature}``, the
    same in every process."""
    text = repr(tuple(
        (name, tuple(sig) if isinstance(sig, list) else sig)
        for name, sig in sorted(files.items())
    ))
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


class ListingWatch:
    # Whether a sweep should re-list known records a slice per refresh
    # instead of all at once every full_sweep_sec (see Sweep).
    rolling = False
    names_at = None  # wall time of the last name_changes (None: unknown)
    from_journal = False  # whether the store's change journal answered it

    def __init__(self, storage, app_name, identity=False):
        self._storage = storage
        self._app_name = app_name
        # A plain local store lists its log files with their identity on
        # request, as a local-first cache over it does (storage.cached).
        self._listing = {"identity": True} if identity else {}
        self._names = {}  # name -> sig at the last name_changes
        self._prints = {}  # key -> fingerprint of its files when last listed
        self._moved = set()  # keys whose baseline changed since baseline(); None: all

    def reset(self):
        self._names, self._prints, self._moved = {}, {}, None

    def baseline(self):
        """``(names, prints, keys moved since the last call or None for
        all)`` — the state :meth:`restore` takes back."""
        moved, self._moved = self._moved, set()
        return self._names, self._prints, moved

    def restore(self, names, prints):
        self._names, self._prints, self._moved = names, prints, set()

    def _moved_keys(self, *keys):
        if self._moved is not None:
            self._moved.update(*keys)

    def name_changes(self, wall=None, journal=False):
        """``(changed {name: sig}, gone names)`` since the last call; None when
        the backend cannot list names. At wall time *wall*, with *journal*,
        the store's change journal may stand in for signing every record
        (:mod:`~vmn_exp.core.index_journal_moves`)."""
        moves = journal_moves(
            self._storage, self._app_name, self._names, self.names_at, wall
        ) if journal and wall is not None else None
        self.from_journal = moves is not None
        if moves is None:
            moves = self._listed_moves()
        if moves is None:
            return None
        changed, gone = moves
        for key in gone:
            del self._names[key]
        self._names.update(changed)
        self.names_at = wall
        self._moved_keys(changed, gone)
        return changed, gone

    def _listed_moves(self):
        names_of = getattr(self._storage, "list_record_names", None)
        names = as_sigs(names_of(self._app_name)) if names_of else None
        if names is None:
            return None
        before = self._names
        changed = {k: sig for k, sig in names.items() if k not in before or before[k] != sig}
        return changed, set(before).difference(names)

    def record_names(self):
        """The names of every record (claims included), or None when the
        backend cannot list them; no baseline moves (any thread may ask)."""
        names_of = getattr(self._storage, "list_record_names", None)
        names = as_sigs(names_of(self._app_name)) if names_of else None
        return None if names is None else set(names)

    def files(self, keys):
        """``{key: {filename: signature}}`` of *keys* (records gone are left out)."""
        if not keys:
            return {}
        return self._storage.list_files(self._app_name, keys=list(keys), **self._listing)

    def full_changes(self):
        """``(files of the records that changed since the last full listing,
        keys of every present record)``."""
        listing = self._storage.list_files(self._app_name, **self._listing)
        prints = {key: _fingerprint(files) for key, files in listing.items()}
        before, self._prints = self._prints, prints
        changed = {k: files for k, files in listing.items() if before.get(k) != prints[k]}
        self._moved_keys(changed, before.keys() - prints.keys())
        return changed, {k for k, files in listing.items() if METADATA_FILE in files}

    def slice_changes(self, keys):
        """``(files of those of *keys* that changed since last listed, keys
        of *keys* gone)`` — a full listing spread over many calls."""
        return self.listed_changes(keys, self.files(keys))

    def listed_changes(self, keys, listing):
        """:meth:`slice_changes` of *keys* listed elsewhere as *listing*."""
        changed = {}
        for key, files in listing.items():
            fingerprint = _fingerprint(files)
            if self._prints.get(key) != fingerprint:
                self._prints[key] = fingerprint
                changed[key] = files
        gone = set(keys).difference(listing)
        for key in gone:
            self._prints.pop(key, None)
        self._moved_keys(changed, gone)
        return changed, gone
