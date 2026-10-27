"""Fakes shared by the journal resume / relisting tests: a local store that
says it is remote (so a journaled index lists behind serving), spied on, and
an in-memory change journal."""
import threading
import time

from vmn_exp.core.journal_keys import JournalKey, encode_key
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
T0 = 1_800_000_000.0


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class FakeJournal:
    def __init__(self):
        self.keys = []

    def put(self, ms, name, app=APP, area="runs"):
        self.keys.append(encode_key(JournalKey(int(ms), area, app, "w", len(self.keys), name)))

    def list(self, prefix, start_after=None):
        for k in sorted(self.keys):
            if k.startswith(prefix) and (start_after is None or k > start_after):
                yield k


class Spy:
    """Every listing *st* answers; ``block_names``/``block_files(n)`` make
    the names listing / the n-th and later keyed listings wait for
    :attr:`release`."""

    def __init__(self, st, monkeypatch):
        self.files, self.names = [], 0
        self.active = self.max_active = 0
        self.release = threading.Event()
        self.block_names, self.block_files_from = False, None
        self._lock = threading.Lock()
        self._list, self._names = st.list_files, st.list_record_names
        monkeypatch.setattr(st, "is_remote", lambda: True, raising=False)
        monkeypatch.setattr(st, "list_files", self.list_files)
        monkeypatch.setattr(st, "list_record_names", self.list_record_names)

    def reset(self):
        self.files, self.names, self.max_active = [], 0, 0

    def list_record_names(self, app_name):
        self.names += 1
        if self.block_names:
            self.release.wait(10)
        return self._names(app_name)

    def list_files(self, app_name, keys=None, **kw):
        with self._lock:
            self.files.append(None if keys is None else set(keys))
            calls = len(self.files)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.block_files_from is not None and calls >= self.block_files_from:
                self.release.wait(10)
            time.sleep(0.02)
            return self._list(app_name, keys=keys, **kw)
        finally:
            with self._lock:
                self.active -= 1


def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def make(st, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    stamp = f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": stamp}, {})
    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    return verstr


def verstrs(index):
    return {r["verstr"] for r in index.rows()}


def progress(index):
    """``(phase, progress)`` of *index*'s freshness."""
    state = index.freshness()
    return state["phase"], state["progress"]


def settle(index, timeout=10.0):
    """Refresh *index* until it says it is idle."""
    deadline = time.monotonic() + timeout
    while True:
        index.refresh()
        if progress(index)[0] == "idle" or time.monotonic() > deadline:
            return index
        time.sleep(0.01)
