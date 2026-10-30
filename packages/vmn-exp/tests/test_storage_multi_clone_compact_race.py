"""A compaction or seal of a run's metrics in one clone while another clone
of the repo (the same writer id) — or another process of the same clone —
ships to it: a segment that lands while the ``.vmx`` is built or uploaded is
neither deleted with the objects the build read nor hidden behind it, and a
clone that keeps shipping from memory after the compaction still reaches
every reader.
"""
import pytest
import vmn_exp.core.metric_compact as metric_compact
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    quietly,
    remote_metric_values,
    stream,
)
from s3_helpers import cached_host, meta, raw_keys
from vmn_exp.core.metric_compact import compact_record, compact_writer, seal_writer
from vmn_exp.core.metric_files import is_indexed_file


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _add(host, *values, start=0):
    assert host.append_metric_block(APP, V, stream(host), block(*values, start=start))
    host.sync_metrics_to_remote(APP, V, stream(host))


def _run_in_clone_a(tmp_path, *values):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    _add(a, *values)
    return a


def _readers(tmp_path):
    return [metric_values(cached_host(tmp_path, root)) for root in "ab"]


def _shared_run(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)
    _add(cached_host(tmp_path, "b"), 2.0, start=10)


def test_a_segment_shipped_while_a_compaction_uploads_survives(tmp_path):
    _shared_run(tmp_path)
    compactor = cached_host(tmp_path, "a")
    real_put, shipped = compactor._remote.put_indexed, []

    def put_indexed(*args, **kw):
        if not shipped:
            shipped.append(True)
            _add(cached_host(tmp_path, "b"), 3.0, start=20)  # b's `add --metrics`
        return real_put(*args, **kw)

    compactor._remote.put_indexed = put_indexed
    assert compact_record(compactor, APP, V)

    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert _readers(tmp_path) == [[1.0, 2.0, 3.0]] * 2


def test_a_segment_shipped_after_a_compaction_read_the_stream_survives(
    tmp_path, monkeypatch
):
    _shared_run(tmp_path)
    real_columns, shipped = metric_compact.writer_columns, []

    def columns(*args, **kw):
        out = real_columns(*args, **kw)
        if not shipped:
            shipped.append(True)
            _add(cached_host(tmp_path, "b"), 5.0, start=50)
        return out

    with monkeypatch.context() as m:
        m.setattr(metric_compact, "writer_columns", columns)
        assert compact_record(cached_host(tmp_path, "a"), APP, V)
    _add(cached_host(tmp_path, "b"), 6.0, start=60)

    assert remote_metric_values() == [1.0, 2.0, 5.0, 6.0]
    assert _readers(tmp_path) == [[1.0, 2.0, 5.0, 6.0]] * 2


def test_a_block_appended_while_its_stream_seals_is_read(tmp_path, monkeypatch):
    a = _run_in_clone_a(tmp_path, 1.0)
    real_columns, appended = metric_compact.writer_columns, []

    def columns(*args, **kw):
        out = real_columns(*args, **kw)
        if not appended:
            appended.append(True)
            _add(a, 5.0, start=50)  # the run logs on while it seals
        return out

    with monkeypatch.context() as m:
        m.setattr(metric_compact, "writer_columns", columns)
        assert seal_writer(a, APP, V, stream(a))
    _add(a, 6.0, start=60)

    assert remote_metric_values() == [1.0, 5.0, 6.0]
    assert _readers(tmp_path) == [[1.0, 5.0, 6.0]] * 2


def test_a_clone_shipping_from_memory_after_another_compacted_reaches_readers(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0)
    b = cached_host(tmp_path, "b")  # long-lived: a notebook reusing its storage
    _add(b, 2.0, start=10)
    assert compact_record(cached_host(tmp_path, "a"), APP, V)  # a's run ended

    _add(b, 3.0, start=20)  # from the sync state b holds
    _add(a, 4.0, start=40)

    assert remote_metric_values() == [1.0, 2.0, 3.0, 4.0]
    assert _readers(tmp_path) == [[1.0, 2.0, 3.0, 4.0]] * 2


def test_a_clone_compacting_alone_leaves_only_its_vmx(tmp_path):
    a = _run_in_clone_a(tmp_path, 1.0)
    _add(a, 2.0, start=10)

    assert compact_writer(cached_host(tmp_path, "a"), APP, V, stream(a))

    names = [k.rsplit("/", 2)[-2:] for k in raw_keys() if "/metrics/" in k]
    assert len(names) == 1 and is_indexed_file("/".join(names[0])), names


def test_a_compaction_whose_vmx_response_was_lost_reads_no_point_twice(tmp_path):
    _shared_run(tmp_path)
    compactor = cached_host(tmp_path, "a")
    client = compactor._remote._s3
    real_put = client.put_object

    def put_object(**kw):  # the .vmx lands, its response is lost
        real_put(**kw)
        if kw["Key"].endswith(".vmx"):
            raise RuntimeError("response lost")

    client.put_object = put_object

    quietly(compact_record, compactor, APP, V)

    assert remote_metric_values() == [1.0, 2.0]
    assert _readers(tmp_path) == [[1.0, 2.0]] * 2


def test_objects_a_failed_delete_left_behind_a_vmx_are_never_read_twice(tmp_path):
    _shared_run(tmp_path)
    compactor = cached_host(tmp_path, "a")
    compactor._remote._delete_keys = lambda keys: None  # every delete fails
    assert compact_record(compactor, APP, V)

    _add(cached_host(tmp_path, "b"), 3.0, start=20)
    compact_record(cached_host(tmp_path, "a"), APP, V)

    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert _readers(tmp_path) == [[1.0, 2.0, 3.0]] * 2


def test_a_process_appending_while_its_clone_compacts_reaches_readers(tmp_path):
    live = _run_in_clone_a(tmp_path, 1.0)  # keeps its storage in memory
    compactor = cached_host(tmp_path, "a")  # another process over clone a's root
    real_put = compactor._local.put_indexed

    def put_indexed(*args, **kw):
        assert live.append_metric_block(APP, V, stream(live), block(2.0, start=10))
        return real_put(*args, **kw)

    compactor._local.put_indexed = put_indexed
    assert compact_writer(compactor, APP, V, stream(compactor))
    live.sync_metrics_to_remote(APP, V, stream(live))

    assert remote_metric_values() == [1.0, 2.0]
    assert _readers(tmp_path) == [[1.0, 2.0]] * 2
