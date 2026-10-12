"""Two clones of one repo on one host record metric points under the same
writer id into the same run (`vmn-exp add --metrics` in one clone, the run in
the other). Every point either clone appends reaches the remote exactly once —
also into a run already compacted, by its own clone or another — and each
clone reads them all.
"""
import pytest
from multi_clone_helpers import (
    APP,
    METRIC_CALLS,
    V,
    block,
    lose_next_response,
    metric_values,
    one_host_bucket,
    remote_metric_values,
    stream,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.core.metric_compact import compact_record, compact_writer
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _add(host, *values, start=0, ship=True):
    assert host.append_metric_block(APP, V, stream(host), block(*values, start=start))
    if ship:
        host.sync_metrics_to_remote(APP, V, stream(host))


def _run_in_clone_a(tmp_path, *values):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    _add(a, *values)
    return a


def _run_ends(host):
    """The run's own end-of-run compaction of its stream."""
    assert compact_writer(host, APP, V, stream(host))


def test_a_fresh_clone_ships_the_points_it_adds_to_a_run(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0, 2.0)

    b = cached_host(tmp_path, "b")
    _add(b, 3.0, start=10)

    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert metric_values(a) == [1.0, 2.0, 3.0]
    assert metric_values(b) == [1.0, 2.0, 3.0]


def test_a_fresh_clone_ships_more_points_than_the_run_holds(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)

    b = cached_host(tmp_path, "b")
    _add(b, 2.0, 3.0, 4.0, 5.0, start=10)

    assert remote_metric_values() == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_points_added_from_another_clone_to_a_compacted_run_ship_and_read(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0, 2.0)
    _run_ends(a)

    b = cached_host(tmp_path, "b")
    _add(b, 3.0, start=10)

    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0, 3.0]


def test_points_added_in_the_clone_that_compacted_the_run_ship_and_read(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0)
    _run_ends(a)

    later = cached_host(tmp_path, "a")
    _add(later, 2.0, start=10)

    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0]


def test_points_added_offline_to_a_compacted_run_are_read(tmp_path):
    storage = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    storage.save(APP, V, meta(V), {})
    _add(storage, 1.0, ship=False)
    _run_ends(storage)

    _add(storage, 2.0, start=10, ship=False)

    assert metric_values(storage) == [1.0, 2.0]


def test_points_a_clone_had_not_shipped_when_another_compacted_its_stream_reach_readers(
    tmp_path,
):
    a = _run_in_clone_a(tmp_path, 1.0)
    _add(a, 2.0, start=10, ship=False)  # the run's last ship failed
    assert compact_record(cached_host(tmp_path, "b"), APP, V)  # `vmn-exp compact`

    _add(cached_host(tmp_path, "a"), 3.0, start=20)  # a later command in clone a

    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0, 3.0]


def test_a_metric_ship_whose_response_was_lost_is_not_shipped_twice(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0)
    _add(a, 2.0, start=10, ship=False)
    lose_next_response(a, METRIC_CALLS)
    with pytest.raises(RuntimeError):
        a.sync_metrics_to_remote(APP, V, stream(a))

    _add(a, 3.0, start=20)

    assert remote_metric_values() == [1.0, 2.0, 3.0]


def test_a_metric_ship_lost_before_the_command_ended_is_not_shipped_twice(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)
    b = cached_host(tmp_path, "b")
    _add(b, 2.0, start=10, ship=False)
    lose_next_response(b, METRIC_CALLS)
    with pytest.raises(RuntimeError):
        b.sync_metrics_to_remote(APP, V, stream(b))

    _add(cached_host(tmp_path, "b"), 3.0, start=20)

    assert remote_metric_values() == [1.0, 2.0, 3.0]


def test_a_lost_metric_ship_another_clone_compacted_since_is_not_shipped_twice(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)
    b = cached_host(tmp_path, "b")
    _add(b, 2.0, start=10, ship=False)
    lose_next_response(b, METRIC_CALLS)
    with pytest.raises(RuntimeError):
        b.sync_metrics_to_remote(APP, V, stream(b))  # landed; b's command ends unaware
    assert compact_record(cached_host(tmp_path, "a"), APP, V)  # takes it in

    _add(cached_host(tmp_path, "b"), 3.0, start=20)

    assert remote_metric_values() == [1.0, 2.0, 3.0]


def test_a_compaction_keeps_points_its_clone_had_not_shipped_yet(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    _add(a, 1.0, ship=False)  # the run's last ship failed
    _add(cached_host(tmp_path, "b"), 2.0, start=10)

    _run_ends(a)

    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(a) == [1.0, 2.0]


def test_a_compaction_keeps_points_another_clone_shipped(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0)
    _add(cached_host(tmp_path, "b"), 2.0, start=10)

    _run_ends(a)

    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(cached_host(tmp_path, "b")) == [1.0, 2.0]


def test_an_index_over_a_clone_that_ships_later_folds_every_point(tmp_path):
    _run_in_clone_a(tmp_path, 3.0)
    b = cached_host(tmp_path, "b")
    _add(b, 4.0, start=10, ship=False)
    index = ExperimentIndex(b, APP, cache_path=str(tmp_path / "idx.sqlite"))
    assert index.refresh().rows()[0]["metric_summary"]["x"]["min"] == 3.0

    b.sync_metrics_to_remote(APP, V, stream(b))
    _add(b, 5.0, start=20)

    rows = index.refresh().rows()
    assert rows == direct_rows(b, APP)[0]
    assert rows[0]["metric_summary"]["x"]["max"] == 5.0
    assert metric_values(b) == [3.0, 4.0, 5.0]
