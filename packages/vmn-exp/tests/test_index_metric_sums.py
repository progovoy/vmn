"""A refold of a record's log folds its writers' metric sums again
(:mod:`vmn_exp.core.fold_sums`) instead of reading their streams: the rows
are what a fresh index folds, NaNs, params and several writers alike."""
import random

from vmn_exp.core.fold_sums import add_block
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
V = "0.0.1-dev.abc.r1"
T0 = 1_700_000_000_000_001


def _storage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    st.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def _points(st, writer, n, rng, step0=0):
    w = MetricWriter(st, APP, V, writer)
    for i in range(n):
        ts = T0 + (step0 + i) * 1000 + rng.randint(0, 999)
        w.add("loss", rng.random(), step=step0 + i, ts_us=ts)
        if rng.random() < 0.5:
            w.add("acc", rng.choice([rng.random(), float("nan")]), step=step0 + i, ts_us=ts)
        if i == 0:
            w.add("once", rng.random(), ts_us=ts + 1)
        if i % 7 == 0:
            w.flush()
    w.flush()


def _fields(row):
    summary = {k: sorted(v.items()) for k, v in row["metric_summary"].items()}
    return repr((sorted(row["metrics"].items()), sorted(summary.items()),
                 row["last_metric_at"], row["params"]))


def _fresh(st, tmp_path):
    return ExperimentIndex(st, APP, str(tmp_path / "fresh.sqlite"))


def _note(st, i):
    st.append_log_entry(APP, V, "a", {"timestamp": us_to_iso(T0 + i), "type": "note",
                                       "note": f"n{i}"})


def test_a_rewritten_log_folds_the_streams_without_reading_them(tmp_path, monkeypatch):
    st = _storage(tmp_path)
    rng = random.Random(7)
    _points(st, "a", 50, rng)
    _points(st, "b", 30, rng, step0=20)
    st.append_log_entry(APP, V, "a", {"timestamp": us_to_iso(T0 + 2), "type": "params",
                                       "params": {"lr": 0.1, "loss": 3.0}})
    _note(st, 3)
    index = ExperimentIndex(st, APP)
    index.refresh()
    first_line = st.load_file(APP, V, "log/a.jsonl").splitlines(keepends=True)[0]
    st.save_file(APP, V, "log/a.jsonl", first_line)
    reads = []
    real = st.read_range
    monkeypatch.setattr(st, "read_range", lambda *a: reads.append(a[2]) or real(*a))

    row = index.refresh().rows()[0]

    assert reads == []
    monkeypatch.setattr(st, "read_range", real)
    assert _fields(row) == _fields(_fresh(st, tmp_path).refresh().rows()[0])


def test_the_streams_grown_since_fold_only_their_growth(tmp_path):
    st = _storage(tmp_path)
    rng = random.Random(8)
    _points(st, "a", 40, rng)
    _note(st, 1)
    index = ExperimentIndex(st, APP)
    index.refresh()
    _points(st, "a", 20, rng, step0=40)
    st.save_file(APP, V, "log/a.jsonl", "")

    row = index.refresh().rows()[0]

    assert _fields(row) == _fields(_fresh(st, tmp_path).refresh().rows()[0])


def test_a_state_persisted_before_sums_still_folds_and_refolds(tmp_path):
    from vmn_exp.core.fold import new_fold
    from vmn_exp.core.index_metrics import metric_signatures, refold_metrics, update_metrics
    from vmn_exp.core.metric_compact import compact_writer

    st = _storage(tmp_path)
    _points(st, "a", 20, random.Random(3))
    assert compact_writer(st, APP, V, "a")
    record = {"fold": new_fold(), "metrics": {"sig": {}, "objects": {}, "points": {}}}
    sigs = metric_signatures(st.record_files(APP, V))

    assert update_metrics(record, st, (APP, V), sigs) is True
    del record["metrics"]["sums"]  # as a state persisted before sums reads back
    record["metrics"]["sig"] = {}
    assert update_metrics(record, st, (APP, V), sigs) is True
    record["fold"] = new_fold()
    refold_metrics(record, st, (APP, V))

    assert record["fold"]["metrics"]["loss"][0] == st.load_merged_log(APP, V)[-1]["values"]["loss"]


def _entry(n, first, last, finite):
    return {"k": "m", "n": n, "has_step": True, "s": [first[1], last[1]],
            "t": [first[2], last[2]], "first": first, "last": last, "sum": finite}


def test_sums_add_up_exactly_and_keep_the_outer_points():
    a = _entry(2, [1.0, 0, 10], [3.0, 1, 20],
               {"n": 2, "sum": 4.0, "parts": [4.0], "min": [1.0, 0, 10], "max": [3.0, 1, 20]})
    b = _entry(1, [float("nan"), 2, 5], [float("nan"), 2, 5],
               {"n": 0, "sum": 0.0, "parts": [], "min": None, "max": None})
    c = _entry(1, [1e16, 3, 30], [1e16, 3, 30],
               {"n": 1, "sum": 1e16, "parts": [1e16], "min": [1e16, 3, 30], "max": [1e16, 3, 30]})
    sums = {}
    for base, entry in ((0, a), (2, b), (3, c)):
        add_block(sums, base, {"keys": [entry]})

    got = sums["m"]
    assert got["n"] == 4 and got["p"] == [2, 3]
    assert got["first"][2] == 5 and got["last"][0] == 1e16
    assert got["sum"]["n"] == 3 and sum(got["sum"]["parts"]) == 4.0 + 1e16
    assert got["sum"]["min"][0] == 1.0 and got["sum"]["max"][0] == 1e16
    assert got["s"] == [0, 3] and got["t"] == [5, 30]
