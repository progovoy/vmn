"""Where a store's change journal lives (plan 11 §5.2): ``<root>/journal/``.

One sink per store root, shared by all its areas. A sink puts empty entries,
lists them for :class:`vmn_exp.core.journal_reader.JournalReader` (its
``list_fn``) and drops whole minute partitions for ``prune``.
"""
import os
import shutil

from vmn_exp.core.journal_keys import JOURNAL_PREFIX
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.s3_base import S3Base


class LocalJournalSink:
    def __init__(self, root):
        self.root = root

    def _path(self, key):
        return os.path.join(self.root, *key.split("/"))

    def put(self, key):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()

    def list(self, prefix, start_after=None):
        try:
            names = sorted(os.listdir(self._path(prefix.rstrip("/"))))
        except FileNotFoundError:
            return
        for name in names:
            key = prefix + name
            if start_after is None or key > start_after:
                yield key

    def partitions(self):
        return [f"{key}/" for key in self.list(JOURNAL_PREFIX)]

    def delete_prefix(self, prefix):
        shutil.rmtree(self._path(prefix.rstrip("/")), ignore_errors=True)


class ObjectJournalSink:
    """The journal of an S3-shaped store (S3, GCS and Azure through
    :mod:`vmn_exp.storage.object_client`), next to its area prefixes."""

    def __init__(self, storage):
        self._storage = storage
        root = storage.prefix.rpartition("/")[0]
        self._base = f"{root}/" if root else ""

    def put(self, key):
        self._storage._put(self._base + key, b"")

    def list(self, prefix, start_after=None):
        params = {"Prefix": self._base + prefix}
        if start_after:
            params["StartAfter"] = self._base + start_after
        for page in self._storage._pages(**params):
            for obj in page.get("Contents", []):
                yield obj["Key"][len(self._base):]

    def partitions(self):
        found = self._storage._common_prefixes(self._base + JOURNAL_PREFIX)
        return [p[len(self._base):] for p in found]

    def delete_prefix(self, prefix):
        keys = [o["Key"] for o in self._storage._objects(self._base + prefix)]
        if keys:
            self._storage._delete_keys(keys)


def sink_for(storage):
    """*storage*'s journal sink, or None for a backend without one."""
    if isinstance(storage, LocalSnapshotStorage):
        return LocalJournalSink(storage.root)
    if isinstance(storage, S3Base):
        return ObjectJournalSink(storage)
    return None


def journal_sinks(storage):
    """The sinks of every journaled store under *storage* (a cache's sides)."""
    sides = (storage, getattr(storage, "_remote", None), getattr(storage, "_local", None))
    sinks = [getattr(side, "_journal_sink", None) for side in sides]
    return [sink for sink in sinks if sink is not None]


def journal_list_fn(storage):
    """``list_fn(prefix, start_after)`` for the journal reader over *storage*
    (a journaled storage, a cache over one, or a bare backend)."""
    sinks = journal_sinks(storage)
    sink = sinks[0] if sinks else sink_for(storage)
    return sink.list
