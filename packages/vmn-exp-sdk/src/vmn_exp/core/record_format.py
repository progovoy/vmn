#!/usr/bin/env python3
"""The on-disk format version of a stored record.

Every new run (and model registry) record carries ``format_version`` in its
``metadata.yml``. It versions the whole record — metadata, the JSONL log
entries and ``run_state.yml`` — so log lines carry no version of their own. A
record without the field predates it and reads as version 1. A reader meeting
a newer version than :data:`RECORD_FORMAT_VERSION` skips the record with a
warning rather than mis-read it: upgrade vmn-exp to see it. The storage
backends apply the gate where they parse metadata (``list_snapshots``,
``load_metadata``) and warn once per record per storage, not on every read.
"""
from vmn_exp._base import VMN_LOGGER

RECORD_FORMAT_VERSION = 1
FORMAT_VERSION_KEY = "format_version"


def stamped(metadata):
    """A copy of *metadata* carrying the format version this code writes."""
    return dict(metadata, **{FORMAT_VERSION_KEY: RECORD_FORMAT_VERSION})


def record_format_version(metadata):
    """*metadata*'s format version; 1 when the record predates the field."""
    return metadata.get(FORMAT_VERSION_KEY, 1)


def readable(metadata, name=None, owner=None):
    """*metadata*, or None when a newer format wrote it.

    The skip is warned about once per record *name* per *owner* (the storage
    the record was read from); without an owner, on every call.
    """
    if metadata is None:
        return None
    version = record_format_version(metadata)
    if isinstance(version, int) and version <= RECORD_FORMAT_VERSION:
        return metadata
    name = name or metadata.get("verstr")
    if _first_sighting(owner, name):
        VMN_LOGGER.warning(
            f"Skipping record {name}: format_version {version} is newer than "
            f"this vmn-exp supports ({RECORD_FORMAT_VERSION}); upgrade vmn-exp "
            f"to read it"
        )
    return None


def _first_sighting(owner, name):
    warned = getattr(owner, "_format_warned", None)
    if warned is None:
        warned = set()
        try:
            owner._format_warned = warned
        except AttributeError:
            return True
    if name in warned:
        return False
    warned.add(name)
    return True
