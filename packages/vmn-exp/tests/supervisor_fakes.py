"""In-memory and tmp_path fakes for `vmn-exp run`'s supervisor uploads."""
import threading

from s3_helpers import meta

from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V = "app", "1.0.0-dev.abc.r1"
WAIT_SEC = 10  # a bound on blocking waits in the tests, never slept


class FakeWait:
    """A retry pause that records its delays and never sleeps; it reports the
    retries abandoned from its *abandon_at*-th call on."""

    def __init__(self, abandon_at=None):
        self.delays = []
        self._abandon_at = abandon_at

    def __call__(self, delay):
        self.delays.append(delay)
        return self._abandon_at is not None and len(self.delays) >= self._abandon_at


class FakeRemote(LocalSnapshotStorage):
    """A tmp_path store that reads as remote. Its run-state saves raise for
    the first *failures* calls; with *hold* (an Event) each waits for it
    first, like a hung PUT. While *logs_down* its log ships raise."""

    def __init__(self, root, failures=0, hold=None):
        super().__init__(root, "runs")
        self.failures = failures
        self.hold = hold
        self.logs_down = False
        self.state_saves = []
        self.saving = threading.Event()

    def is_remote(self):
        return True

    def save_file(self, app_name, verstr, filename, data):
        if filename == RUN_STATE_FILE:
            self._save_state(data)
        return super().save_file(app_name, verstr, filename, data)

    def _save_state(self, data):
        self.saving.set()
        if self.hold is not None:
            self.hold.wait(WAIT_SEC)
        self.state_saves.append(data)
        if self.failures:
            self.failures -= 1
            raise OSError("bucket down")

    def cache_identity(self):
        if self.logs_down:
            raise OSError("bucket down")  # the first call of every log ship
        return super().cache_identity()


def local_first(tmp_path, remote, on_remote=True):
    """A checkout's local-first store over *remote* holding run ``V``
    (only locally unless *on_remote*)."""
    local = LocalSnapshotStorage(str(tmp_path / "local"), "runs")
    if on_remote:
        storage = CachedSnapshotStorage(local, remote)
        storage.save(APP, V, meta(V), {})
        return storage
    local.save(APP, V, meta(V), {})
    return CachedSnapshotStorage(local, remote)


def remote_state(remote):
    return remote.load_file(APP, V, RUN_STATE_FILE)
