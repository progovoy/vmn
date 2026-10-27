"""A live run ships a metric segment per sync, and every remote reader (the
index's refolds, a chart's series, store upkeep's compaction) GETs each one.
The stream's owner rolls what it shipped up into a ``.vmx`` while live —
every ``LIVE_ROLLUP_SEGMENTS`` shipped, all but the last
``LIVE_ROLLUP_LAG``, built from its local stream outside its ship lock and
put under it — so a reader sees one ``.vmx`` and a few segments, and
shipping goes on in the same stream past it."""
import os
import threading

import pytest
from s3_helpers import cached_host, meta, mocked_bucket, raw_keys, s3_storage
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_compact import compact_writer, writer_columns
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.storage import cached_metrics, metric_rollup, ship_state
from vmn_exp.storage.ship_state import finalizing

APP, V, W = "app", "1.0.0-dev.abc.0001", "w"
T0 = 1_767_225_600_000_001
ROLLUP, LAG = 4, 1


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    monkeypatch.setattr(cached_metrics, "LIVE_ROLLUP_SEGMENTS", ROLLUP)
    monkeypatch.setattr(cached_metrics, "LIVE_ROLLUP_LAG", LAG)
    with mocked_bucket(monkeypatch):
        yield


@pytest.fixture
def host(tmp_path):
    host = cached_host(tmp_path, "a")
    host.save(APP, V, meta(V), {})
    return host


def _ship(host, start, stop):
    for i in range(start, stop):
        block = encode_block({"x": Columns([i, i], [T0 + 2 * i, T0 + 2 * i + 1], [i, -i])})
        host.append_metric_block(APP, V, W, block)
        host.sync_metrics_to_remote(APP, V, W)


def _remote():
    return s3_storage().metric_objects(APP, V)[W]


def _values():
    storage = s3_storage()
    return list(writer_columns(storage, APP, V, storage.metric_objects(APP, V)[W])["x"].values)


def _expected(n):
    return [v for i in range(n) for v in (float(i), float(-i))]


def _metric_keys():
    return [k for k in raw_keys() if "/metrics/" in k]


def test_a_live_streams_segments_are_rolled_up_as_they_ship(host):
    _ship(host, 0, 3 * ROLLUP + 3)

    objects = _remote()
    assert is_indexed_file(objects[0][0])
    assert len(objects) <= 1 + ROLLUP + LAG
    assert len(_metric_keys()) == len(objects)  # nothing it covers is left behind
    assert _values() == _expected(3 * ROLLUP + 3)


def test_shipping_resumes_past_the_rollup_in_a_new_process(host, tmp_path):
    _ship(host, 0, ROLLUP + 2)

    again = cached_host(tmp_path, "a")  # the ship state and the listing, read anew
    _ship(again, ROLLUP + 2, 2 * ROLLUP + 3)

    assert is_indexed_file(_remote()[0][0])
    assert _values() == _expected(2 * ROLLUP + 3)


def test_a_lost_ship_state_resumes_past_the_rollup_in_the_same_stream(host):
    _ship(host, 0, ROLLUP + 2)
    record = host._local.local_record_dir(APP, V)
    os.unlink(os.path.join(record, ship_state.SHIP_DIR, "metrics.json"))

    _ship(host, ROLLUP + 2, ROLLUP + 4)

    assert list(s3_storage().metric_objects(APP, V)) == [W]
    assert _values() == _expected(ROLLUP + 4)


def test_the_index_folds_the_rollups_like_the_segments(host, tmp_path):
    index = ExperimentIndex(s3_storage(), APP, os.path.join(tmp_path, "i.sqlite"), full_sweep_sec=0)
    for start in range(0, 3 * ROLLUP, 2):
        _ship(host, start, start + 2)
        row = index.refresh().rows()[0]

    fresh = ExperimentIndex(s3_storage(), APP, os.path.join(tmp_path, "f.sqlite"), full_sweep_sec=0)
    assert row["metric_summary"] == fresh.refresh().rows()[0]["metric_summary"]
    assert row["metric_summary"]["x"]["max"] == 3 * ROLLUP - 1


def test_the_index_swaps_folded_segments_for_the_rollup_for_its_footer(host, tmp_path):
    from s3_helpers import record_calls

    index = ExperimentIndex(s3_storage(), APP, os.path.join(tmp_path, "i.sqlite"), full_sweep_sec=0)
    _ship(host, 0, ROLLUP + LAG)
    index.refresh()
    _ship(host, ROLLUP + LAG, ROLLUP + LAG + 1)  # rolls 0..ROLLUP up
    assert is_indexed_file(_remote()[0][0])

    calls = record_calls(index._storage._s3)
    row = index.refresh().rows()[0]

    metric_gets = [p["Key"] for op, p in calls if op == "GetObject" and "/metrics/" in p["Key"]]
    assert len(metric_gets) <= 2  # the .vmx footer, the segment after it
    assert row["metric_summary"]["x"]["max"] == ROLLUP + LAG


def test_a_finished_stream_still_ends_as_one_vmx(host):
    _ship(host, 0, 2 * ROLLUP + 2)

    assert compact_writer(host, APP, V, W)

    assert [is_indexed_file(n) for n, _ in _remote()] == [True]
    assert _values() == _expected(2 * ROLLUP + 2)


def test_a_finalizer_ship_never_rolls_up(host):
    _ship(host, 0, ROLLUP + LAG)

    with finalizing():
        _ship(host, ROLLUP + LAG, ROLLUP + LAG + 1)  # the segment a periodic sync rolls up at

    assert not any(is_indexed_file(n) for n, _ in _remote())


def test_an_exit_flush_never_rolls_up():
    from vmn_exp.storage import buffered
    from vmn_exp.storage.buffered import BufferedRemoteStorage

    pod = BufferedRemoteStorage(s3_storage(), area="runs", flush_interval_sec=0)
    try:
        pod.save(APP, V, meta(V), {})
        for i in range(ROLLUP + LAG):
            pod.append_metric_block(APP, V, W, encode_block({"x": Columns([i], [T0 + i], [i])}))
        pod._flush_interval_sec = 3600  # the next block waits for the exit flush
        pod.append_metric_block(APP, V, W, encode_block({"x": Columns([9], [T0 + 9], [9])}))

        pod.close()

        assert len(_remote()) == ROLLUP + LAG + 1
        assert not any(is_indexed_file(n) for n, _ in _remote())
    finally:
        buffered.close_all()


def test_a_stream_past_the_byte_cap_is_not_rolled_up(host, monkeypatch):
    monkeypatch.setattr(cached_metrics, "LIVE_ROLLUP_MAX_BYTES", 100)

    _ship(host, 0, 2 * ROLLUP + 2)

    assert len(_remote()) == 2 * ROLLUP + 2


def test_the_rollup_is_built_outside_the_ship_lock(host, monkeypatch):
    lock_path = os.path.join(host._local.local_record_dir(APP, V), ship_state.SHIP_DIR, "lock")
    free = []
    real = metric_rollup.build

    def build(*args):
        lock = ship_state._thread_lock(lock_path)
        other = threading.Thread(target=lambda: free.append(lock.acquire(timeout=1) and
                                                            (lock.release() or True)))
        other.start()
        other.join()
        return real(*args)

    monkeypatch.setattr(metric_rollup, "build", build)
    _ship(host, 0, ROLLUP + LAG + 1)

    assert free == [True]
    assert is_indexed_file(_remote()[0][0])
