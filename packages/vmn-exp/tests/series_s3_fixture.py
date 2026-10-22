"""A finished, compacted run on a moto S3 store, and a round-trip latency
injected into every S3 call, for the single-run series request tests."""
import contextlib
import os
import tempfile
import threading
import time

import yaml

from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage import s3_stats

APP, V = "app", "1.0.0-dev.a"
T0 = 1_700_000_000_000_000
POINTS = 3000


def compacted_run(storage, tmp_path):
    """*V* with a create/define_metric log, one compacted writer of two
    metrics and a finished run state."""
    storage.save(APP, V, {"verstr": V, "timestamp": us_to_iso(T0)}, {})
    storage.append_log_entry(APP, V, "w", {"timestamp": us_to_iso(T0), "type": "create",
                                           "params": {"lr": 0.1}})
    storage.append_log_entry(APP, V, "w", {"timestamp": us_to_iso(T0 + 1),
                                           "type": "define_metric", "name": "acc",
                                           "goal": "max"})
    steps = list(range(POINTS))
    stamps = [T0 + 10 * i for i in steps]
    cols = {"loss": Columns(steps, stamps, [1.0 / (i + 1) for i in steps]),
            "acc": Columns(steps, stamps, [i / POINTS for i in steps])}
    fd, path = tempfile.mkstemp(dir=str(tmp_path), suffix=".vmx")
    with os.fdopen(fd, "wb") as f:
        f.write(build_index("w", cols))
    assert storage.put_indexed(APP, V, "w", path)
    storage.save_file(APP, V, RUN_STATE_FILE, yaml.dump({"state": "finished", "exit_code": 0}))


class CallLog:
    """Every S3 call (``s3_stats`` listener) with its start/end times."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, call):
        end = time.monotonic()
        with self._lock:
            self.calls.append((end - call.duration_ms / 1000, end, call.operation, call.key))

    def ops(self):
        return [op for _, _, op, _ in sorted(self.calls)]

    def critical_path(self):
        """The longest chain of calls each starting after the previous ended."""
        calls = sorted(self.calls)
        depth = []
        for i, (start, _, _, _) in enumerate(calls):
            before = [depth[j] for j, c in enumerate(calls[:i]) if c[1] <= start]
            depth.append(1 + max(before, default=0))
        return max(depth, default=0)


@contextlib.contextmanager
def recorded_calls(client, latency):
    """A :class:`CallLog` of *client*'s calls, each delayed by *latency* s."""
    log = CallLog()

    def delay(**_):
        time.sleep(latency)

    client.meta.events.register("before-send.s3", delay)
    s3_stats.add_listener(log)
    try:
        yield log
    finally:
        s3_stats.remove_listener(log)
        client.meta.events.unregister("before-send.s3", delay)
