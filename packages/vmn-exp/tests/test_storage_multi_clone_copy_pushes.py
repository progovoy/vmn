"""`vmn-exp push` from an offline ``cp -r`` copy of a root: the copy holds a
stale prefix of the original's streams and pushes none of them, so it can
neither replace the original's ``.vmx`` nor compact its log segments under
the original's live ship."""
import shutil
from collections import Counter

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    one_host_bucket,
    remote_metric_values,
    stream,
    tag,
)
from s3_helpers import cached_host, meta, s3_storage
from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.push_logs import push_logs
from vmn_exp.core.push_metrics import push_metrics
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.core.writer import own_stream
from vmn_exp.storage.local import LocalSnapshotStorage

FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _local(tmp_path, name):
    return LocalSnapshotStorage(str(tmp_path / name), "runs")


def test_pushing_metrics_from_a_copy_keeps_the_points_the_original_pushed(tmp_path):
    s3_storage().create_exclusive(APP, V, meta(V), {})
    a = _local(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = own_stream(a, APP, V)
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    assert compact_writer(a, APP, V, own)
    push_metrics(a, s3_storage(), APP, V)

    push_metrics(_local(tmp_path, "a2"), s3_storage(), APP, V)

    assert remote_metric_values() == [1.0, 2.0]


def _remote_tag_counts():
    logs = s3_storage().load_logs_by_writer(APP, V)
    return Counter(k for entries in logs.values() for e in entries
                   if e.get("type") == "tags" for k in e["set"])


def test_pushing_logs_from_a_copy_keeps_the_lines_the_original_ships_later(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.sync_log_to_remote(APP, V, own)
    a.append_log_entry(APP, V, own, tag(2, "k2"))  # its ship failed
    shutil.copytree(tmp_path / "a", tmp_path / "a2")
    push_logs(_local(tmp_path, "a2"), s3_storage(), APP, V, finished=True)
    a.append_log_entry(APP, V, own, tag(3, "k3"))
    a.save_file(APP, V, RUN_STATE_FILE, FINISHED)

    a.sync_log_to_remote(APP, V, own)

    assert _remote_tag_counts() == {"k1": 1, "k2": 1, "k3": 1}


def test_a_moved_offline_root_pushes_its_log_and_metrics(tmp_path):
    s3_storage().create_exclusive(APP, V, meta(V), {})
    a = _local(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = own_stream(a, APP, V)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    shutil.move(str(tmp_path / "a"), str(tmp_path / "b"))
    b = _local(tmp_path, "b")

    push_logs(b, s3_storage(), APP, V, finished=True)
    push_metrics(b, s3_storage(), APP, V)

    assert _remote_tag_counts() == {"k1": 1}
    assert remote_metric_values() == [1.0]
