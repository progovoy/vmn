"""A plugin store with the base ``is_remote()`` (False) becomes the local root
itself (``CachedSnapshotStorage(store, None)``): the cache keeps calling its
listing hooks with the documented signatures, ``list_files(app_name[, keys])``
and ``record_files(app_name, verstr)``, so such a store lists and indexes."""

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.storage.base import SnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

_SIG = {"metadata.yml": (1, 2)}
_METADATA = b"verstr: v\ntimestamp: '2026-01-01T00:00:00Z'\nformat_version: 2\n"


class _OldSignatureStore(SnapshotStorage):
    """A minimal plugin root: listing hooks without the ``identity`` flag."""

    area = "runs"

    def list_files(self, app_name, keys=None):
        return {"v": dict(_SIG)}

    def record_files(self, app_name, verstr):
        return dict(_SIG) if verstr == "v" else {}

    def list_record_names(self, app_name):
        return {"v": None}

    def load_file(self, app_name, verstr, filename):
        return _METADATA if filename == "metadata.yml" else None

    def load_record(self, app_name, verstr):
        return None, {}

    def list_snapshots(self, app_name):
        return []

    def list_apps(self):
        return []

    def save(self, app_name, verstr, metadata, patches):
        pass

    def save_file(self, app_name, verstr, filename, data):
        return True

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        return True

    def update_note(self, app_name, verstr, note):
        return True

    def delete(self, app_name, verstr):
        pass

    def local_record_dir(self, app_name, verstr):
        return None


def test_cached_plugin_root_lists_all_files_with_the_old_signature():
    storage = CachedSnapshotStorage(_OldSignatureStore(), None)

    assert storage.list_files("app") == {"v": _SIG}


def test_cached_plugin_root_lists_keyed_files_with_the_old_signature():
    storage = CachedSnapshotStorage(_OldSignatureStore(), None)

    assert storage.list_files("app", keys=["v", "gone"]) == {"v": _SIG}


def test_cached_plugin_root_indexes_with_the_old_signature():
    storage = CachedSnapshotStorage(_OldSignatureStore(), None)

    rows = ExperimentIndex(storage, "app").refresh().rows()

    assert [row["verstr"] for row in rows] == ["v"]
