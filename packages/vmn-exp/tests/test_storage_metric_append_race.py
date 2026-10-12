"""Two processes or threads of one root: a metric block appended while the
other compacts the stream (a seal, run end) lands either in the file the
build reads or in the copy's next stream, never in a file the compaction
drops. The appender is held between choosing its stream and writing."""
import threading

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    remote_metric_values,
    stream,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.writer import own_stream
from vmn_exp.storage import local_metrics
from vmn_exp.storage.local import LocalSnapshotStorage

# How long the held append waits for the compaction it raced to finish.
_HOLD_SEC = 1.5


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _compact_during_next_append(monkeypatch, compact):
    real, threads = local_metrics._append, []

    def append(path, data):
        if not threads:
            threads.append(threading.Thread(target=compact))
            threads[0].start()
            threads[0].join(_HOLD_SEC)
        return real(path, data)

    monkeypatch.setattr(local_metrics, "_append", append)
    return threads


def test_a_block_appended_while_another_process_compacts_reaches_the_remote(
        tmp_path, monkeypatch):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    assert a.append_metric_block(APP, V, stream(a), block(1.0, start=1))
    a.sync_metrics_to_remote(APP, V, stream(a))
    compactor, appender = cached_host(tmp_path, "a"), cached_host(tmp_path, "a")
    threads = _compact_during_next_append(
        monkeypatch, lambda: compact_writer(compactor, APP, V, stream(compactor)))

    assert appender.append_metric_block(APP, V, stream(appender), block(2.0, start=2))
    threads[0].join()
    for host in (compactor, appender):
        host.sync_metrics_to_remote(APP, V, stream(host))

    assert remote_metric_values() == [1.0, 2.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0]


def test_a_block_appended_while_an_offline_root_compacts_is_kept(tmp_path, monkeypatch):
    root = LocalSnapshotStorage(str(tmp_path / "a"), "runs")
    assert root.create_exclusive(APP, V, meta(V), {})
    own = own_stream(root, APP, V)
    assert root.append_metric_block(APP, V, own, block(1.0, start=1))
    threads = _compact_during_next_append(
        monkeypatch, lambda: compact_writer(root, APP, V, own))

    assert root.append_metric_block(APP, V, own, block(2.0, start=2))
    threads[0].join()

    assert metric_values(root) == [1.0, 2.0]
