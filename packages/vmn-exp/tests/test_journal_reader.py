from vmn_exp.core.journal_keys import JournalKey, encode_key
from vmn_exp.core.journal_reader import JournalReader

T0 = 1_700_000_000.0


class FakeStore:
    def __init__(self):
        self.keys = []
        self.calls = []

    def put(self, ms, app="a", name="r", area="runs", seq=0, writer="w"):
        key = JournalKey(int(ms), area, app, writer, seq, name)
        self.keys.append(encode_key(key))

    def list(self, prefix, start_after):
        self.calls.append((prefix, start_after))
        for k in sorted(self.keys):
            if k.startswith(prefix) and (start_after is None or k > start_after):
                yield k


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _reader(store, clock, **kw):
    return JournalReader(store.list, clock, **kw)


def _names(result):
    return sorted(k.name for ks in result.entries.values() for k in ks)


def test_reads_each_entry_once_grouped_by_scope():
    s, c = FakeStore(), Clock(T0)
    r = _reader(s, c)
    s.put(T0 * 1000 - 1000, app="a", name="r1")
    s.put(T0 * 1000 - 500, app="b", name="r2", area="snapshots")
    res = r.tick()
    assert [k.name for k in res.entries[("runs", "a")]] == ["r1"]
    assert [k.name for k in res.entries[("snapshots", "b")]] == ["r2"]
    assert res.overflow == set()
    c.t += 1
    assert r.tick().entries == {}


def test_entries_ordered_by_time():
    s, c = FakeStore(), Clock(T0)
    s.put(T0 * 1000 - 100, name="late")
    s.put(T0 * 1000 - 200, name="early")
    res = _reader(s, c).tick()
    assert [k.name for k in res.entries[("runs", "a")]] == ["early", "late"]


def test_minute_rollover():
    base = (int(T0) // 60) * 60 + 59.5
    s, c = FakeStore(), Clock(base)
    r = _reader(s, c)
    r.tick()
    c.t = base + 1
    s.put(c.t * 1000 - 100, name="next_minute")
    s.put(base * 1000 + 100, name="old_minute")
    assert _names(r.tick()) == ["next_minute", "old_minute"]


def test_writer_four_minutes_behind_is_read_six_is_not():
    s, c = FakeStore(), Clock(T0)
    r = _reader(s, c)
    r.tick()
    c.t = T0 + 10
    s.put((c.t - 240) * 1000, name="four")
    s.put((c.t - 360) * 1000, name="six")
    assert _names(r.tick()) == ["four"]


def test_overflow_scope_reported_not_returned():
    s, c = FakeStore(), Clock(T0)
    for i in range(11):
        s.put(T0 * 1000 - 100, app="big", seq=i)
    s.put(T0 * 1000 - 100, app="small")
    res = _reader(s, c, max_per_scope=10).tick()
    assert res.overflow == {("runs", "big")}
    assert list(res.entries) == [("runs", "small")]


def test_default_cutoff_is_10k():
    s, c = FakeStore(), Clock(T0)
    for i in range(10_001):
        s.put(T0 * 1000 - 100, seq=i)
    assert _reader(s, c).tick().overflow == {("runs", "a")}


def test_200_apps_cost_one_list_per_partition():
    s, c = FakeStore(), Clock(T0)
    r = _reader(s, c)
    r.tick()
    c.t += 2
    s.calls.clear()
    for i in range(200):
        s.put(c.t * 1000 - 100, app=f"app{i}")
    res = r.tick()
    assert len(res.entries) == 200
    prefixes = [p for p, _ in s.calls]
    assert len(prefixes) == len(set(prefixes)) <= 7


def test_cursor_serializes_and_resumes():
    s, c = FakeStore(), Clock(T0)
    r = _reader(s, c)
    r.tick()
    state = r.cursor
    assert JournalReader.from_cursor(state, s.list, c).cursor == state
    c.t += 30
    s.put(c.t * 1000 - 10, name="new")
    r2 = JournalReader.from_cursor(state, s.list, c)
    assert _names(r2.tick()) == ["new"]
    assert r2.cursor["last_seen_ms"] == int(c.t * 1000)


def test_resumed_cursor_skips_keys_seen_at_its_boundary_ms():
    s, c = FakeStore(), Clock(T0)
    r = _reader(s, c, skew_window_sec=0)
    r.tick()
    s.put(c.t * 1000, name="same_ms")
    assert _names(r.tick()) == ["same_ms"]
    r2 = JournalReader.from_cursor(r.cursor, s.list, c, skew_window_sec=0)
    s.put(c.t * 1000, name="later_same_ms", seq=1)
    assert _names(r2.tick()) == ["later_same_ms"]


def test_filters_client_side_and_skips_garbage_keys():
    s, c = FakeStore(), Clock(T0)
    s.put(T0 * 1000 - 100, name="ok")
    s.put((T0 - 301) * 1000, name="before_window")
    s.keys.append(encode_key(JournalKey(int(T0 * 1000), "runs", "a", "w", 0, "x"))
                  .rsplit("/", 1)[0] + "/garbage")

    def no_start_after(prefix, start_after):  # Azure-style listing
        return [k for k in s.keys if k.startswith(prefix)]

    assert _names(JournalReader(no_start_after, c).tick()) == ["ok"]
