"""A real :class:`SnapshotStorage` holding nothing, for duck-typed test fakes.

Subclass it and override only what a test needs; everything else — ``in_area``
(whose areas are empty ``EmptyStorage`` instances) and any later interface
addition — comes from the real base.
"""
from vmn_exp.storage.base import SnapshotStorage


class EmptyStorage(SnapshotStorage):
    def save(self, app_name, verstr, metadata, patches):
        pass

    def load_record(self, app_name, verstr):
        return None, None

    def list_snapshots(self, app_name):
        return []

    def update_note(self, app_name, verstr, note):
        return False

    def delete(self, app_name, verstr):
        pass

    def load_file(self, app_name, verstr, filename):
        return None

    def save_file(self, app_name, verstr, filename, data):
        pass

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        pass

    def local_record_dir(self, app_name, verstr):
        return None

    def _open_area(self, name):
        return EmptyStorage()
