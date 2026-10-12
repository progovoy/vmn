"""Two clones of one repo on one host ship metric points under the same writer
id. A remote read that fails (a network blip, not a missing object) never
passes for an absent or empty object: a ship or a compaction it would mislead
fails instead, and the next one ships and keeps every point exactly once.
"""
import pytest
from multi_clone_helpers import (
    APP,
    METRIC_CALLS,
    V,
    block,
    fail_once,
    lose_next_response,
    metric_values,
    one_host_bucket,
    quietly,
    remote_metric_values,
    stream,
)
from s3_helpers import cached_host, meta
from vmn_exp.core.metric_compact import compact_record, compact_writer


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _run_in_clone_a(tmp_path, *values):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    _add(a, *values)
    return a


def _add(host, *values, start=0, ship=True):
    assert host.append_metric_block(APP, V, stream(host), block(*values, start=start))
    if ship:
        host.sync_metrics_to_remote(APP, V, stream(host))


def _ship_everywhere(tmp_path):
    for root in "ab":
        host = cached_host(tmp_path, root)
        host.sync_metrics_to_remote(APP, V, stream(host))


def test_a_failed_read_of_a_lost_upload_never_ships_it_twice(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)
    b = cached_host(tmp_path, "b")
    _add(b, 2.0, start=10, ship=False)
    lose_next_response(b, METRIC_CALLS)
    with pytest.raises(RuntimeError):
        b.sync_metrics_to_remote(APP, V, stream(b))  # landed

    later = cached_host(tmp_path, "b")
    hit = fail_once(later, "list_objects_v2", "/metrics/")
    _add(later, 3.0, start=20, ship=False)
    quietly(later.sync_metrics_to_remote, APP, V, stream(later))
    assert hit
    _ship_everywhere(tmp_path)

    assert remote_metric_values() == [1.0, 2.0, 3.0]


def test_a_compaction_whose_segment_read_failed_keeps_the_points(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)
    b = cached_host(tmp_path, "b")
    _add(b, 2.0, start=10)
    _add(b, 3.0, start=20)  # b's stream: segments 0 and 1
    compactor = cached_host(tmp_path, "a")
    hit = fail_once(compactor, "get_object", "@000001.vms")

    quietly(compact_record, compactor, APP, V)

    assert hit
    assert remote_metric_values() == [1.0, 2.0, 3.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0, 3.0]


def test_a_compaction_whose_record_check_failed_keeps_unshipped_points(tmp_path):
    _run_in_clone_a(tmp_path, 1.0)
    _add(cached_host(tmp_path, "b"), 2.0, 3.0, start=10)
    _add(cached_host(tmp_path, "a"), 4.0, start=40, ship=False)  # a's ship failed
    compactor = cached_host(tmp_path, "a")
    hit = fail_once(compactor, "get_object", "metadata.yml")

    quietly(lambda: compact_writer(compactor, APP, V, stream(compactor)))
    assert hit
    _ship_everywhere(tmp_path)

    assert remote_metric_values() == [1.0, 2.0, 3.0, 4.0]
    assert metric_values(cached_host(tmp_path, "a")) == [1.0, 2.0, 3.0, 4.0]


def test_a_clone_whose_ship_state_was_lost_never_ships_its_points_twice(tmp_path):
    import shutil

    _run_in_clone_a(tmp_path, 1.0)
    _add(cached_host(tmp_path, "b"), 2.0, start=10)
    _add(cached_host(tmp_path, "a"), 3.0, start=20)
    record = cached_host(tmp_path, "a")._local.local_record_dir(APP, V)
    shutil.rmtree(f"{record}/.ship")

    _add(cached_host(tmp_path, "a"), 4.0, start=30)

    assert remote_metric_values() == [1.0, 2.0, 3.0, 4.0]
