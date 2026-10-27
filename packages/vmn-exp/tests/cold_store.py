"""An in-memory remote store for cold index loads: record names a page at a
time, file listings that can be held, counted and slowed down."""
import threading
import time

APP = "app"
FINISHED = b"state: finished\nexit_code: 0\n"


def verstr(i):
    return f"0.0.1-dev.abc.r{i:05d}"


class ColdStore:
    """*n* finished runs, ``r00000`` the oldest; names listed *page* at a time.

    ``hold_names_after(p)``: name pages past the *p*-th wait for
    :attr:`release`; ``hold_files_after(n)``: file listings wait once *n*
    records were listed. :attr:`listed` counts the records listed."""

    def __init__(self, n, page=1000, listing_sec=0.0):
        self.names = [verstr(i) for i in range(n)]
        self.page, self.listing_sec = page, listing_sec
        self.release = threading.Event()
        self.names_hold = self.files_hold = None
        self.listed = self.name_pages = 0
        self._lock = threading.Lock()

    def is_remote(self):
        return True

    def hold_names_after(self, pages):
        self.names_hold = pages

    def hold_files_after(self, records):
        self.files_hold = records

    def record_name_pages(self, app_name):
        for start in range(0, len(self.names), self.page):
            if self.names_hold is not None and self.name_pages >= self.names_hold:
                self.release.wait(30)
            self.name_pages += 1
            yield self.names[start:start + self.page]

    def list_record_names(self, app_name):
        return dict.fromkeys(name for page in self.record_name_pages(app_name) for name in page)

    def _files(self, keys):
        with self._lock:
            held = self.files_hold is not None and self.listed >= self.files_hold
        if held:
            self.release.wait(30)
        time.sleep(self.listing_sec)
        with self._lock:
            self.listed += len(keys)
        known = set(self.names)
        return {k: self._record_files(k) for k in keys if k in known}

    def _record_files(self, key):
        mtime = 1_800_000_000.0 + int(key[-5:])
        return {"metadata.yml": (40, mtime, f"m{key}"), "run_state.yml": (30, mtime, f"s{key}")}

    def list_files(self, app_name, keys=None, **kwargs):
        return self._files(list(self.names if keys is None else keys))

    def list_files_between(self, app_name, names):
        return self._files(list(names))

    def load_file(self, app_name, key, filename):
        if filename == "metadata.yml":
            i = int(key[-5:])
            return (f"verstr: {key}\nformat_version: 2\n"
                    f"timestamp: '2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}Z'\n")
        if filename == "run_state.yml":
            return FINISHED.decode()
        return None
