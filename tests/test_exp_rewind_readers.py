"""Every log reader honours a rewind: the experiment index (incrementally,
across writers), the run page's parsed-log cache and S3 merged logs."""
import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.core import index as experiment_index
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.log import load_log, metric_series
from vmn_exp.snapshot import get_snapshot_storage
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP = "app"
V = "1.0.0-dev.a"


def _ts(i):
    return f"2026-01-01T00:00:{i:02d}.000000Z"


def _metric(i, step, loss):
    return {"timestamp": _ts(i), "type": "metrics", "step": step, "values": {"loss": loss}}


def _rewind(i, step):
    return {"timestamp": _ts(i), "type": "rewind", "step": step}


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(experiment_index, "_monotonic", lambda: now[0])
    return now


@pytest.fixture
def storage(tmp_path):
    (tmp_path / ".git").mkdir()
    s = get_snapshot_storage("local", vmn_root_path=str(tmp_path), subdir="experiments")
    s.save(APP, V, {"verstr": V, "timestamp": _ts(0)}, {})
    s.save_file(APP, V, "run_state.yml", "state: running\n")
    for i, loss in ((1, 1.0), (2, 0.5), (3, 0.25)):
        s.append_log_entry(APP, V, "old", _metric(i, i, loss))
    return s


def _loss(index, clock):
    clock[0] += 1
    index.refresh()
    return index.rows()[0]["metrics"]["loss"]


def test_the_index_forgets_what_a_rewind_hides(storage, clock):
    index = ExperimentIndex(storage, APP, full_sweep_sec=300)
    assert _loss(index, clock) == 0.25

    storage.append_log_entry(APP, V, "new", _rewind(4, 1))
    assert _loss(index, clock) == 1.0

    storage.append_log_entry(APP, V, "new", _metric(5, 2, 0.7))
    assert _loss(index, clock) == 0.7


def test_a_rewound_old_writer_that_appends_later_still_counts(storage, clock):
    index = ExperimentIndex(storage, APP, full_sweep_sec=300)
    storage.append_log_entry(APP, V, "new", _rewind(4, 1))
    assert _loss(index, clock) == 1.0
    storage.append_log_entry(APP, V, "old", _metric(6, 3, 0.1))
    assert _loss(index, clock) == 0.1


def test_the_parsed_log_cache_drops_rewound_points(storage):
    cache = ParsedLogs()
    snap = cache.get(storage, APP, V, load_log)
    assert [p["step"] for p in snap.series()["loss"]] == [1, 2, 3]

    storage.append_log_entry(APP, V, "new", _rewind(4, 1))
    storage.append_log_entry(APP, V, "new", _metric(5, 2, 0.7))
    snap = cache.get(storage, APP, V, load_log)
    assert [(p["step"], p["value"]) for p in snap.series()["loss"]] == [(1, 1.0), (2, 0.7)]
    assert snap.metrics == {"loss": 0.7}
    assert snap.series() == metric_series(load_log(storage, APP, V))


def test_s3_merged_logs_honour_a_rewind(monkeypatch):
    with mocked_bucket(monkeypatch):
        s3 = s3_storage()
        s3.save(APP, V, {"verstr": V, "timestamp": _ts(0)}, {})
        s3.append_log_entries(APP, V, "old", [_metric(1, 1, 1.0), _metric(2, 2, 0.5)])
        s3.append_log_entries(APP, V, "new", [_rewind(3, 1), _metric(4, 2, 0.7)])
        series = metric_series(load_log(s3, APP, V))
        assert [(p["step"], p["value"]) for p in series["loss"]] == [(1, 1.0), (2, 0.7)]
