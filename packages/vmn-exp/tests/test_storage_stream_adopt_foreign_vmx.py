"""A remote ``.vmx`` of an inherited stream need not hold all a copy has:
another clone's ``vmn-exp compact`` builds it from what the original shipped,
not from what the original appended. Adopt deletes the copy's files of such a
stream only when the ``.vmx`` provably holds every point of them; otherwise
it refuses for the run (nothing deleted or rewritten, the stream stays
inherited), and the note fires as for any stream the remote lacks."""
import logging
import os
import shutil

import pytest
from multi_clone_helpers import (
    APP,
    V,
    block,
    metric_values,
    one_host_bucket,
    remote_metric_values,
    stream,
    tag,
)
from s3_helpers import cached_host, meta, op_counts, record_calls, s3_storage
from vmn_exp.core.adopt import missing_inherited
from vmn_exp.core.metric_compact import compact_record


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with one_host_bucket(monkeypatch):
        yield


def _copy_under_foreign_vmx(tmp_path):
    """The original ships 1.0, appends 2.0 and dies; another clone compacts
    the remote ([1.0]); the original's dir is then moved away to b."""
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_log_entry(APP, V, own, tag(1, "k1"))
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    a.sync_log_to_remote(APP, V, own)
    a.sync_metrics_to_remote(APP, V, own)
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    assert compact_record(cached_host(tmp_path, "c"), APP, V) == [own]
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    shutil.rmtree(tmp_path / "a")
    return cached_host(tmp_path, "b"), own


def _files(root):
    out = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                out[os.path.relpath(path, root)] = (f.read(), os.stat(path).st_mtime_ns)
    return out


def _record_files(host):
    return {k: v for k, v in _files(host._local.local_record_dir(APP, V)).items()
            if not any(part.startswith(".") for part in k.split(os.sep))}


def test_the_note_fires_when_a_foreign_vmx_lacks_points_of_the_copy(tmp_path):
    b, own = _copy_under_foreign_vmx(tmp_path)

    assert missing_inherited(b._local, s3_storage(), APP, V) == [own]


def test_adopt_refuses_and_keeps_the_points_a_foreign_vmx_lacks(tmp_path):
    b, own = _copy_under_foreign_vmx(tmp_path)
    before = _record_files(b)

    with pytest.raises(Exception) as refused:
        b.adopt_streams(APP, V)

    assert "\n" not in str(refused.value) and "remote" in str(refused.value)
    assert _record_files(b) == before
    assert missing_inherited(b._local, s3_storage(), APP, V) == [own]
    assert metric_values(b._local) == [1.0, 2.0]
    b.sync_metrics_to_remote(APP, V, stream(b))
    assert remote_metric_values() == [1.0]


def test_the_original_itself_recovers_after_a_foreign_vmx(tmp_path):
    a = cached_host(tmp_path, "a")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = stream(a)
    a.append_metric_block(APP, V, own, block(1.0, start=1))
    a.sync_metrics_to_remote(APP, V, own)
    a.append_metric_block(APP, V, own, block(2.0, start=2))
    compact_record(cached_host(tmp_path, "c"), APP, V)
    a2 = cached_host(tmp_path, "a")
    a2.sync_metrics_to_remote(APP, V, stream(a2))

    assert remote_metric_values() == [1.0, 2.0]


def test_a_copy_lists_the_remote_for_its_note_once_per_run(tmp_path, caplog):
    b, _ = _copy_under_foreign_vmx(tmp_path)
    own = stream(b)
    with caplog.at_level(logging.WARNING):
        b.sync_log_to_remote(APP, V, own)
        b.sync_metrics_to_remote(APP, V, own)
    calls = record_calls(b._remote._s3)

    for _ in range(3):
        b.sync_log_to_remote(APP, V, own)
        b.sync_metrics_to_remote(APP, V, own)

    assert op_counts(calls).get("ListObjectsV2", 0) == 0, op_counts(calls)


def test_the_note_names_other_views_of_the_folder_and_when_to_adopt(tmp_path, caplog):
    b, _ = _copy_under_foreign_vmx(tmp_path)

    with caplog.at_level(logging.WARNING):
        b.sync_metrics_to_remote(APP, V, stream(b))

    notes = [r.getMessage() for r in caplog.records if "--adopt" in r.getMessage()]
    assert len(notes) == 1
    assert "another checkout" in notes[0] and "another view of this folder" in notes[0]
    assert "never write" in notes[0]


def _put_vmx(storage, own, tmp_path, values, rewinds_applied=False):
    from vmn_exp.core.metric_columns import Columns
    from vmn_exp.core.metric_index_file import build_index

    at = list(range(1, len(values) + 1))
    path = tmp_path / f"{len(values)}.vmx"
    path.write_bytes(build_index(own, {"x": Columns(at, at, list(values))}, rewinds_applied))
    assert storage.put_indexed(APP, V, own, str(path))


def test_a_rewound_local_vmx_is_never_taken_as_covered_by_a_bigger_remote_one(tmp_path):
    from vmn_exp.core.adopt import adopt_streams
    from vmn_exp.core.writer import own_stream
    from vmn_exp.storage.local import LocalSnapshotStorage

    remote = s3_storage()
    remote.create_exclusive(APP, V, meta(V), {})
    a = LocalSnapshotStorage(str(tmp_path / "a"), "runs")
    assert a.create_exclusive(APP, V, meta(V), {})
    own = own_stream(a, APP, V)
    # the original rewound past step 1 and logged 9.0 anew: its .vmx has 2 points
    _put_vmx(a, own, tmp_path, [1.0, 9.0], rewinds_applied=True)
    # another clone compacted the 3 points the original had shipped before
    _put_vmx(remote, own, tmp_path, [1.0, 2.0, 3.0])
    shutil.copytree(tmp_path / "a", tmp_path / "b")
    shutil.rmtree(tmp_path / "a")
    b = LocalSnapshotStorage(str(tmp_path / "b"), "runs")

    assert missing_inherited(b, remote, APP, V) == [own]
    with pytest.raises(ValueError):
        adopt_streams(b, remote, APP, V)
    assert metric_values(b) == [1.0, 9.0]
