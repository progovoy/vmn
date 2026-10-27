"""A journal reader catching up after a long stop: it never lists further
back than the journal keeps, it lists many minute partitions on several
threads, and an overflowing scope still names the records it overflowed
with."""
import threading
import time

from vmn_exp.core.journal_keys import JournalKey, encode_key
from vmn_exp.core.journal_reader import JournalReader

T0 = 1_700_000_000.0
DAY_MS = 86_400_000


class FakeStore:
    def __init__(self):
        self.keys, self.prefixes = [], []
        self.active = self.max_active = 0
        self._lock = threading.Lock()

    def put(self, ms, name, app="a"):
        self.keys.append(encode_key(JournalKey(int(ms), "runs", app, "w", len(self.keys), name)))

    def list(self, prefix, start_after):
        with self._lock:
            self.prefixes.append(prefix)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.001)
            return [k for k in sorted(self.keys)
                    if k.startswith(prefix) and (start_after is None or k > start_after)]
        finally:
            with self._lock:
                self.active -= 1


def test_a_cursor_older_than_the_lookback_lists_only_the_lookback():
    store = FakeStore()
    now_ms = T0 * 1000
    store.put(now_ms - 3 * DAY_MS, "expired")
    store.put(now_ms - DAY_MS, "kept")
    reader = JournalReader(store.list, lambda: T0, skew_window_sec=0,
                           last_seen_ms=int(now_ms - 5 * DAY_MS), max_lookback_sec=2 * 86_400)
    result = reader.tick()
    assert [k.name for k in result.entries[("runs", "a")]] == ["kept"]
    assert len(store.prefixes) <= 2 * 24 * 60 + 2


def test_many_partitions_are_listed_on_several_threads():
    store = FakeStore()
    now_ms = T0 * 1000
    for minute in range(0, 600, 7):
        store.put(now_ms - minute * 60_000, f"r{minute}")
    serial = JournalReader(store.list, lambda: T0, skew_window_sec=0,
                           last_seen_ms=int(now_ms - 600 * 60_000)).tick()
    store.max_active = 0
    parallel = JournalReader(store.list, lambda: T0, skew_window_sec=0, workers=8,
                             last_seen_ms=int(now_ms - 600 * 60_000)).tick()
    assert parallel.entries == serial.entries
    assert store.max_active > 1


def test_an_overflowing_scope_names_its_records():
    store = FakeStore()
    for i in range(3):
        store.put(T0 * 1000 - 1000 + i, f"r{i}")
    store.put(T0 * 1000 - 500, "r0")
    result = JournalReader(store.list, lambda: T0, max_per_scope=2).tick()
    assert result.overflow == {("runs", "a")}
    assert result.overflow_names == {("runs", "a"): {"r0", "r1", "r2"}}
    assert ("runs", "a") not in result.entries
