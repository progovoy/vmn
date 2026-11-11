"""A tmp_path bucket for direct-to-bucket ship tests: no S3, no network."""
import threading

from vmn_exp.core.logfiles import log_object_name
from vmn_exp.core.metric_files import stream_name
from vmn_exp.storage.local import LocalSnapshotStorage

WAIT_SEC = 10  # a bound on blocking waits in the tests, never slept
HANG_SEC = 60  # how long a held create hangs unless released


class FakeBucket(LocalSnapshotStorage):
    """A local store that reads as remote and counts its segment creates;
    with *hold* (a ``threading.Event``) each create waits for it first, like
    a store that hangs."""

    def __init__(self, root, hold=None):
        super().__init__(root, "runs")
        self.creates = 0
        self.creating = threading.Event()
        self._hold = hold

    def is_remote(self):
        return True

    def load_logs_by_writer(self, app_name, verstr, writers=None):
        logs = super().load_logs_by_writer(app_name, verstr)
        return {w: log for w, log in logs.items() if writers is None or w in writers}

    def create_log_segment(self, app_name, verstr, stream, seq, data):
        return self._create(app_name, verstr, log_object_name(stream, seq), data)

    def create_metric_segment(self, app_name, verstr, stream, seq, data):
        return self._create(app_name, verstr, stream_name(stream, seq), data)

    def _create(self, app_name, verstr, name, data):
        self.creates += 1
        self.creating.set()
        if self._hold is not None:
            self._hold.wait(HANG_SEC)
        self.save_file(app_name, verstr, name, data)
        return True
