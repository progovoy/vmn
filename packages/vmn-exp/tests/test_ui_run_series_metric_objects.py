"""``run_series`` (Compare, outer-run Charts) reads metric objects, not the log.

It used to rebuild the whole merged log — one dict per metric point — just to
thin each series. It now answers from the run's metric objects like a zoom
(:mod:`~vmn_exp.ui.readers.range_series`) and must give the payload the parsed
log gives: series, totals, step metrics, ``x`` joins, rewinds, v1 entries.
"""
import os
import random
import tempfile

import pytest
from s3_helpers import meta

from vmn_exp.core.log import load_log
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_entries import record_metric_entries
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.core.metric_time import us_to_iso
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.readers import experiment_detail
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP, V = "app", "1.0.0-dev.a"
T0 = 1_700_000_000_000_000


def _stamps(rng, n):
    """*n* distinct, increasing timestamps (us)."""
    return sorted(rng.sample(range(T0, T0 + 50 * n), n))


def _streamed(storage, rng, stamps):
    entries = []
    for i, ts in enumerate(stamps):
        values = {"loss": rng.random(), "epoch": float(i // 10)}
        if rng.random() < 0.1:
            values["loss"] = float("nan")
        entries.append({"timestamp": us_to_iso(ts), "type": "metrics", "step": i,
                        "values": values})
    w = MetricWriter(storage, APP, V, "w")
    for i in range(0, len(entries), 7):
        assert record_metric_entries(w, entries[i:i + 7])


def _compacted(storage, rng, stamps, tmp_path):
    steps = list(range(len(stamps)))
    cols = {"acc": Columns(steps, stamps, [rng.random() for _ in steps])}
    fd, path = tempfile.mkstemp(dir=tmp_path, suffix=".vmx")
    with os.fdopen(fd, "wb") as f:
        f.write(build_index("c", cols))
    assert storage.put_indexed(APP, V, "c", path)


def _jsonl(storage, rng, stamps, rewind_at):
    for i, ts in enumerate(stamps):
        storage.append_log_entry(APP, V, "j", {
            "timestamp": us_to_iso(ts), "type": "metrics", "step": i,
            "values": {"old": rng.random(), "loss": rng.random()}})
    storage.append_log_entry(APP, V, "j", {
        "timestamp": us_to_iso(T0 + 1), "type": "define_metric", "name": "acc",
        "step_metric": "epoch"})
    storage.append_log_entry(APP, V, "j", {
        "timestamp": us_to_iso(rewind_at), "type": "rewind", "step": 120})


@pytest.fixture
def storage(tmp_path):
    rng = random.Random(7)
    storage = LocalSnapshotStorage(str(tmp_path / "store"), "runs")
    storage.save(APP, V, meta(V), {})
    stamps = _stamps(rng, 1200)
    _streamed(storage, rng, stamps[0::3])
    _compacted(storage, rng, stamps[1::3], tmp_path)
    _jsonl(storage, rng, stamps[2::3][:150], rewind_at=stamps[900])
    return storage


@pytest.fixture
def no_merged_log(monkeypatch):
    def refuse(self, app_name, verstr):
        raise AssertionError("run_series rebuilt the merged log")

    class _NoParse:
        def get(self, *args):
            raise AssertionError("run_series parsed the whole log")

    monkeypatch.setattr(LocalSnapshotStorage, "load_merged_log", refuse)
    monkeypatch.setattr(experiment_detail, "_PARSED", _NoParse())


def _old_path(storage, keys, max_points, budget, x, schema):
    snapshot = ParsedLogs().get(storage, APP, V, load_log)
    series, totals = experiment_detail.thinned_series(snapshot, keys, max_points, budget, x)
    return series, totals, snapshot.step_metrics(schema)


def _sorted(value):
    if isinstance(value, dict):
        return {k: _sorted(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted(v) for v in value]
    return value


def _canonical(payload):
    """The payload with every dict's keys sorted (JSON key order carries
    nothing), NaN made comparable."""
    return repr(_sorted(list(payload)))


CASES = [
    dict(keys=None, max_points=2000, budget=None, x=None),
    dict(keys=None, max_points=40, budget=None, x=None),
    dict(keys=["loss", "nope"], max_points=17, budget=None, x=None),
    dict(keys=None, max_points=2000, budget=30, x=None),
    dict(keys=None, max_points=50, budget=None, x="epoch"),
    dict(keys=["acc", "loss"], max_points=25, budget=None, x={"acc": "epoch"}),
]


@pytest.mark.parametrize("case", CASES)
def test_run_series_matches_the_parsed_log(storage, case):
    expected = _old_path(storage, schema=None, **case)
    assert expected[0]  # the fixture has series to compare
    got = experiment_detail.run_series(storage, APP, V, schema=None, **case)
    assert _canonical(got) == _canonical(expected)


def test_run_series_never_rebuilds_the_merged_log(storage, no_merged_log):
    series, totals, declared = experiment_detail.run_series(storage, APP, V)
    assert set(series) == {"loss", "acc", "epoch", "old"}
    assert declared == {"acc": "epoch"}


def test_run_series_of_a_gone_run_is_none(storage):
    assert experiment_detail.run_series(storage, APP, "1.0.0-dev.gone") is None
