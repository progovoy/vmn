"""A schema view of a new index generation costs what changed, not the index.

At 705k runs one ``summarized`` took 76-125 s while every request for that
schema waited on it: each generation walked every row again (and a run
inserted mid-order, moving every later row's ``idx``, summarized all of them
afresh). A new generation now summarizes only its changed rows, and a
request arriving while another thread computes the next view is served the
previous one instead of waiting.
"""
import dataclasses
import gc
import threading
import time
import types

import pytest
from vmn_exp.core import index_views
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache
from vmn_exp.core.index_views import SchemaRows, kept_lean

SCHEMA = {"loss": {"goal": "min"}}
SUMMARY = {"loss": {"last": 0.5, "first": 0.9, "mean": 0.6, "min": 0.1, "max": 0.9}}


@pytest.fixture
def calls(monkeypatch):
    seen, real = [], index_views.summarized_row

    def counting(row, parts, policies):
        seen.append(row["verstr"])
        return real(row, parts, policies)

    monkeypatch.setattr(index_views, "summarized_row", counting)
    return seen


def _lean(pos, n):
    row = {"verstr": f"0.0.{n}", "idx": pos + 1, "parent": None, "metrics": {"loss": 0.5}}
    return kept_lean((row, None, (SUMMARY, None), None, None, None, None, None, None, None))


class _Index:
    """Records published through a :class:`RowCache`, as an index does."""

    def __init__(self, n):
        self.cache, self.generation = RowCache(), 0
        self.order = [f"k{i:06d}" for i in range(0, 2 * n, 2)]
        self.records = {}
        for pos, key in enumerate(self.order):
            self._put(key, pos)

    def _put(self, key, pos):
        n = int(key[1:])
        self.records[key] = {"meta": {"verstr": f"0.0.{n}"}, "rs_sig": None, "run_state": None}
        self.cache.pop(key)
        self.cache.seed({key: _lean(pos, n)})

    def publish(self, touched=None):
        self.generation += 1
        return self.cache.snapshot("app", self.generation, self.order, self.records, touched)

    def change(self, pos):
        key = self.order[pos]
        self._put(key, pos)
        return self.publish({key})

    def insert(self, pos):
        key = f"k{2 * pos + 1:06d}"  # sorts between its neighbours
        self.order.insert(pos, key)
        self._put(key, pos)
        return self.publish({key})


def test_a_generation_with_one_changed_row_summarizes_only_that_row(calls):
    index = _Index(300)
    index.publish().summarized(SCHEMA)
    calls.clear()
    view = index.change(150).summarized(SCHEMA)
    assert calls == [view.rows[150]["verstr"]]
    assert view.rows[150]["metrics"]["loss"] == 0.1


def test_a_run_inserted_mid_order_summarizes_only_that_run(calls):
    index = _Index(300)
    first = index.publish().summarized(SCHEMA)
    calls.clear()
    view = index.insert(150).summarized(SCHEMA)
    assert calls == ["0.0.301"]
    assert [r["idx"] for r in view.rows] == list(range(1, 302))
    assert all(r["metrics"]["loss"] == 0.1 for r in view.rows)
    moved = view.row("0.0.300")  # was rows[150], renumbered
    assert moved is view.rows[151] and moved is not first.rows[150]


class _Watched(dict):
    """A row counting the reads made of it."""

    reads = [0]

    def __getitem__(self, key):
        self.reads[0] += 1
        return super().__getitem__(key)


def _snapshot(rows, memo):
    parts = {r["verstr"]: (SUMMARY, None) for r in rows}
    built = IndexSnapshot.build("app", 1, rows, {}, metric_parts=parts)
    return dataclasses.replace(built, _schema_rows=memo)


def test_a_new_generation_reads_only_its_changed_rows():
    rows = [_Watched(verstr=f"0.0.{i}", idx=i + 1, metrics={"loss": 0.5}) for i in range(500)]
    memo = SchemaRows()
    _snapshot(rows, memo).summarized(SCHEMA)
    rows[250] = _Watched(rows[250], metrics={"loss": 0.4})
    second = _snapshot(rows, memo)
    _Watched.reads[0] = 0
    view = second.summarized(SCHEMA)
    assert _Watched.reads[0] <= 10
    assert view.row("0.0.250")["metrics"]["loss"] == 0.1


def test_a_request_is_served_the_previous_view_while_another_computes_the_next(monkeypatch):
    index = _Index(50)
    first = index.publish().summarized(SCHEMA)
    second = index.change(10)
    entered, release, real = threading.Event(), threading.Event(), index_views.summarized_row

    def gated(row, parts, policies):
        if threading.current_thread() is computing:
            entered.set()
            assert release.wait(30)
        return real(row, parts, policies)

    monkeypatch.setattr(index_views, "summarized_row", gated)
    computed = []
    computing = threading.Thread(target=lambda: computed.append(second.summarized(SCHEMA)))
    computing.start()
    try:
        assert entered.wait(30)
        served, done = [], threading.Event()
        threading.Thread(target=lambda: (served.append(second.summarized(SCHEMA, stale_ok=True)),
                                         done.set()),
                         daemon=True).start()
        assert done.wait(2), "a request waited for another thread's computation"
        assert served == [first]
    finally:
        release.set()
        computing.join(timeout=30)
    assert computed[0].generation == second.generation
    assert second.summarized(SCHEMA) is computed[0]


def _timed(snapshot):
    """Seconds to summarize *snapshot*, the collector off: its pauses,
    proportional to the whole heap, would swamp the ratios."""
    gc.collect()
    gc.disable()
    try:
        started = time.perf_counter()
        snapshot.summarized(SCHEMA)
        return time.perf_counter() - started
    finally:
        gc.enable()


@pytest.mark.serial
def test_bench_a_new_generation_of_200k_rows_costs_what_changed():
    index = _Index(200_000)
    cold = _timed(index.publish())
    times = {"one changed": _timed(index.change(100_000)),
             "inserted mid-order": _timed(index.insert(150_000)),
             "unchanged": _timed(index.publish(set()))}
    print(f"\ncold {cold * 1000:.0f} ms; " + "; ".join(
        f"{name} {t * 1000:.1f} ms" for name, t in times.items()))
    moved = times.pop("inserted mid-order")  # renumbers a quarter of the rows
    assert moved < cold / 4, (cold, moved)
    assert all(t < cold / 10 for t in times.values()), (cold, times)


class _Computing:
    """Another thread computing *snapshot*'s view, held inside the
    computation until :meth:`release` (or *after* seconds)."""

    def __init__(self, monkeypatch, snapshot, after=None):
        self.entered, self._release = threading.Event(), threading.Event()
        real = index_views.summarized_row

        def gated(row, parts, policies):
            if threading.current_thread() is self._thread:
                self.entered.set()
                assert self._release.wait(30)
            return real(row, parts, policies)

        monkeypatch.setattr(index_views, "summarized_row", gated)
        self.views = []
        self._thread = threading.Thread(target=lambda: self.views.append(snapshot.summarized(SCHEMA)))
        self._thread.start()
        assert self.entered.wait(30)
        if after is not None:
            threading.Timer(after, self._release.set).start()

    def release(self):
        self._release.set()
        self._thread.join(timeout=30)


def test_a_caller_not_opting_into_stale_gets_its_own_generation(monkeypatch):
    index = _Index(50)
    first = index.publish().summarized(SCHEMA)  # still served, so kept alive
    second = index.change(10)
    computing = _Computing(monkeypatch, second, after=0.2)
    try:
        assert second.summarized(SCHEMA).generation == second.generation != first.generation
    finally:
        computing.release()


def test_the_view_served_stale_never_goes_back_a_generation(monkeypatch):
    index = _Index(50)
    older, newer = index.publish(), index.change(5)
    kept = newer.summarized(SCHEMA)
    older.summarized(SCHEMA)  # a request still holding the older generation
    third = index.change(10)
    computing = _Computing(monkeypatch, third)
    try:
        assert third.summarized(SCHEMA, stale_ok=True) is kept
    finally:
        computing.release()


class _Leader:
    leading = True


def test_the_search_rows_writer_writes_the_generation_it_was_given(monkeypatch):
    from vmn_exp.ui import search_rows_writer

    index = _Index(50)
    first = index.publish().summarized(SCHEMA)  # still served, so kept alive
    second = index.change(10)
    written, real = [], search_rows_writer.search_rows
    monkeypatch.setattr(search_rows_writer, "search_rows",
                        lambda snap: written.append(snap.generation) or real(snap))
    writer = search_rows_writer.SearchRowsWriter(types.SimpleNamespace(write=lambda *a: None))
    leader = _Leader()
    writer.note(leader, "ws", "app", lambda: SCHEMA)
    computing = _Computing(monkeypatch, second, after=0.2)
    try:
        writer.refreshed(leader, second)
    finally:
        computing.release()
    assert written == [second.generation] != [first.generation]


def test_the_board_warmer_warms_the_generation_it_was_given(monkeypatch):
    from vmn_exp.ui.leaderboard_warm import BoardWarmer

    index = _Index(50)
    first = index.publish().summarized(SCHEMA)  # still served, so kept alive
    second = index.change(10)
    warmed = []
    cache = types.SimpleNamespace(conf_of=lambda snap: (SCHEMA, None),
                                  _base=lambda board: warmed.append(board.generation))
    computing = _Computing(monkeypatch, second, after=0.2)
    try:
        BoardWarmer(cache).warm(second)
    finally:
        computing.release()
    assert warmed == [second.generation] != [first.generation]
