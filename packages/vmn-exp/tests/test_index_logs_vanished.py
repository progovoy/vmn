"""A record's listing can go stale under the index: a remote cold load reads a
stuck run's first log objects, publishes its row and folds the rest later
from the same listing, while store upkeep compacts the run in between (the
merged object replaces the listed segments). The index then misses one
listed segment, not every one of them, and folds the merged log once."""
import json

from vmn_exp.core.index_logs import update_logs
from vmn_exp.core.index_record import new_record
from vmn_exp.core.index_rows_first import first_objects
from vmn_exp.core.logfiles import compacted_log_name, log_object_name, parse_jsonl

APP, V = "app", "v1"
N = 20


def _line(i):
    return json.dumps({"type": "params", "params": {f"p{i}": i},
                       "timestamp": f"2026-01-01T00:00:{i:02d}Z"}) + "\n"


class _Store:
    """One writer's log segments; every read of a name not there is a miss."""

    def __init__(self):
        self.files = {log_object_name("w", i): _line(i).encode() for i in range(N)}
        self.misses = 0

    def sigs(self):
        return {name: [len(data), 0.0, "e"] for name, data in self.files.items()}

    def compact(self):
        merged = b"".join(self.files[log_object_name("w", i)] for i in range(N))
        self.files = {compacted_log_name("w", N - 1): merged}

    def metric_objects(self, app_name, verstr):
        return {}

    def read_file_from(self, app_name, verstr, name, offset):
        data = self.files.get(name)
        if data is None:
            self.misses += 1
            return None
        return data[offset:]

    def load_logs_by_writer(self, app_name, verstr):
        return {"w": [e for data in self.files.values()
                      for e in parse_jsonl(data.decode(), "w")]}


def test_a_compaction_after_the_listing_costs_one_miss_and_folds_everything():
    store = _Store()
    listed = store.sigs()
    record = new_record()
    update_logs(record, store, store, APP, V, first_objects(listed))
    store.compact()

    update_logs(record, store, store, APP, V, listed)

    assert store.misses <= 1
    assert sorted(record["fold"]["params"]) == sorted(f"p{i}" for i in range(N))
