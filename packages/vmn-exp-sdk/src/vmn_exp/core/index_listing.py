#!/usr/bin/env python3
"""A storage's listings as *changes* since the previous listing, for
:mod:`experiment_index_sweep`.

At 100k records the listings themselves are cheap next to what a caller does
with them per record, so this reports only what moved: the names whose
signature changed (or appeared) and the names gone since the previous
``name_changes``, and the records whose files differ from the last time a
full listing (``full_changes``) saw them. The same class runs in the index's process or, for a plain
local store, in its I/O helper process (:mod:`experiment_index_io_process`),
where the baselines live next to the listings and only changes cross the pipe.

A caller that failed to apply a change calls :meth:`reset`: the next listings
then report everything again.
"""
METADATA_FILE = "metadata.yml"


def as_sigs(names):
    """``{name: sig}`` from a backend's names listing (a plain set of names:
    all-None sigs); None stays None."""
    if names is None or isinstance(names, dict):
        return names
    return dict.fromkeys(names)


def _fingerprint(files):
    """A cheap equality stand-in for a record's ``{name: signature}``."""
    return hash(tuple(
        (name, tuple(sig) if isinstance(sig, list) else sig)
        for name, sig in sorted(files.items())
    ))


class ListingWatch:
    def __init__(self, storage, app_name):
        self._storage = storage
        self._app_name = app_name
        self._names = {}  # name -> sig at the last name_changes
        self._prints = {}  # key -> fingerprint of its files when last listed

    def reset(self):
        self._names, self._prints = {}, {}

    def name_changes(self):
        """``(changed {name: sig}, gone names)`` since the last call; None when
        the backend cannot list names."""
        names_of = getattr(self._storage, "list_record_names", None)
        names = as_sigs(names_of(self._app_name)) if names_of else None
        if names is None:
            return None
        before, self._names = self._names, names
        changed = {k: sig for k, sig in names.items() if k not in before or before[k] != sig}
        return changed, set(before).difference(names)

    def files(self, keys):
        """``{key: {filename: signature}}`` of *keys* (records gone are left out)."""
        return self._storage.list_files(self._app_name, keys=list(keys)) if keys else {}

    def full_changes(self):
        """``(files of the records that changed since the last full listing,
        keys of every present record)``."""
        listing = self._storage.list_files(self._app_name)
        prints = {key: _fingerprint(files) for key, files in listing.items()}
        before, self._prints = self._prints, prints
        changed = {k: files for k, files in listing.items() if before.get(k) != prints[k]}
        return changed, {k for k, files in listing.items() if METADATA_FILE in files}
