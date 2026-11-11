"""A dict-backed :class:`SnapshotStorage` for the conformance kit's own tests.

:class:`MemoryStorage` is atomic (a lock guards ``create_exclusive``);
:class:`CheckThenSaveStorage` checks, then saves, and its ``exists`` holds
every racing thread at a barrier, so all of them see the name free.
"""
import threading

from vmn_exp.storage.base import SnapshotStorage
from vmn_exp.storage.files import METADATA_FILE


class MemoryStorage(SnapshotStorage):
    def __init__(self):
        self.files = {}  # {(app, verstr): {filename: bytes}}
        self.metadata = {}  # {(app, verstr): dict}
        self._lock = threading.Lock()

    def save(self, app_name, verstr, metadata, patches):
        self.files.setdefault((app_name, verstr), {}).update(
            {name: text for name, text in patches.items() if isinstance(text, str)}
        )
        self.metadata[(app_name, verstr)] = dict(metadata)

    def create_exclusive(self, app_name, verstr, metadata, patches):
        with self._lock:
            if (app_name, verstr) in self.metadata:
                return False
            self.save(app_name, verstr, metadata, patches)
            return True

    def load_record(self, app_name, verstr):
        metadata = self.metadata.get((app_name, verstr))
        if metadata is None:
            return None, None
        return dict(metadata), dict(self.files.get((app_name, verstr), {}))

    def load_metadata(self, app_name, verstr):
        return self.load_record(app_name, verstr)[0]

    def list_snapshots(self, app_name):
        return [dict(m) for (app, _), m in self.metadata.items() if app == app_name]

    def list_apps(self):
        return sorted({app for app, _ in self.metadata})

    def update_note(self, app_name, verstr, note):
        return self.update_metadata(app_name, verstr, {"note": note})

    def update_metadata(self, app_name, verstr, updates):
        if (app_name, verstr) not in self.metadata:
            return False
        self.metadata[(app_name, verstr)].update(updates)
        return True

    def delete(self, app_name, verstr):
        self.metadata.pop((app_name, verstr), None)
        self.files.pop((app_name, verstr), None)

    def load_file(self, app_name, verstr, filename):
        return self.files.get((app_name, verstr), {}).get(filename)

    def save_file(self, app_name, verstr, filename, data):
        if filename == METADATA_FILE:
            raise ValueError("this fake keeps metadata apart")
        self.files.setdefault((app_name, verstr), {})[filename] = data
        return True

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        raise NotImplementedError

    def local_record_dir(self, app_name, verstr):
        return None


class CheckThenSaveStorage(MemoryStorage):
    def __init__(self, racers):
        super().__init__()
        self._race = threading.Barrier(racers)

    def exists(self, app_name, verstr):
        found = (app_name, verstr) in self.metadata
        if threading.current_thread() is not threading.main_thread():
            self._race.wait()  # every racer has looked before any saves
        return found

    def create_exclusive(self, app_name, verstr, metadata, patches):
        if self.exists(app_name, verstr):
            return False
        self.save(app_name, verstr, metadata, patches)
        return True
