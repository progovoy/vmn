"""Every local copy of a record appends to its own streams: a stream key is
``<writer id>~<owner>``, the owner a random id the record copy keeps (a copy
of the directory elsewhere, a copy deleted and fetched again, a stream once
compacted: a new owner). Without a local copy (straight to a bucket) the
owner is the process's; a log buffer's is its own.
"""
import os
import shutil

import pytest
from multi_clone_helpers import block
from s3_helpers import cached_host, meta, mocked_bucket, s3_storage
from vmn_exp.core import writer
from vmn_exp.core.manage import tag_run
from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.streams import display_writer, stream_key
from vmn_exp.core.writer import get_writer_id, own_stream
from vmn_exp.storage import buffered
from vmn_exp.storage.buffered import BufferedRemoteStorage
from vmn_exp.storage.cached import CachedSnapshotStorage
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V = "app", "0.0.1-dev.aaa1111.bbb2222"


@pytest.fixture(autouse=True)
def _writer(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "gpu07")
    writer._WRITER_ID = None


def _local(root):
    storage = CachedSnapshotStorage(LocalSnapshotStorage(str(root), "runs"))
    if not storage.exists(APP, V):
        storage.save(APP, V, meta(V), {})
    return storage


def test_a_stream_is_the_writer_id_and_its_owner(tmp_path):
    stream = own_stream(_local(tmp_path / "a"), APP, V)

    writer_id, sep, owner = stream.partition("~")
    assert (writer_id, sep) == ("gpu07", "~") and owner
    assert stream == stream_key("gpu07", owner)
    assert display_writer(stream) == "gpu07"
    assert display_writer("gpu07") == "gpu07"


def test_processes_over_one_record_copy_share_its_stream(tmp_path):
    first = own_stream(_local(tmp_path / "a"), APP, V)

    assert own_stream(_local(tmp_path / "a"), APP, V) == first


def test_two_clones_get_two_streams(tmp_path):
    assert own_stream(_local(tmp_path / "a"), APP, V) != own_stream(
        _local(tmp_path / "b"), APP, V)


def test_a_copied_root_gets_a_stream_of_its_own(tmp_path):
    original = own_stream(_local(tmp_path / "a"), APP, V)
    shutil.copytree(tmp_path / "a", tmp_path / "copy")

    assert own_stream(_local(tmp_path / "copy"), APP, V) != original
    assert own_stream(_local(tmp_path / "a"), APP, V) == original


def test_a_root_moved_across_filesystems_gets_a_stream_of_its_own_and_keeps_shipping_the_old(
        tmp_path):
    original = own_stream(_local(tmp_path / "a"), APP, V)
    shutil.copytree(tmp_path / "a", tmp_path / "b")  # shutil.move across devices
    shutil.rmtree(tmp_path / "a")
    moved = _local(tmp_path / "b")

    assert own_stream(moved, APP, V) != original
    assert own_stream(_local(tmp_path / "b"), APP, V) == own_stream(moved, APP, V)
    assert original.partition("~")[2] in moved._local.inherited_owners(APP, V)


def test_a_root_renamed_on_its_filesystem_keeps_its_stream(tmp_path):
    original = own_stream(_local(tmp_path / "a"), APP, V)
    shutil.move(str(tmp_path / "a"), str(tmp_path / "b"))

    assert own_stream(_local(tmp_path / "b"), APP, V) == original


def test_a_root_seen_through_a_symlink_keeps_its_stream(tmp_path):
    original = own_stream(_local(tmp_path / "a"), APP, V)
    os.symlink(str(tmp_path / "a"), str(tmp_path / "alink"))

    assert own_stream(_local(tmp_path / "alink"), APP, V) == original
    assert own_stream(_local(tmp_path / "a"), APP, V) == original


def test_an_owner_file_from_before_identities_counts_as_another_directory(tmp_path):
    import json

    storage = _local(tmp_path / "a")
    original = own_stream(storage, APP, V)
    path = os.path.join(storage.local_record_dir(APP, V), ".stream-owner")
    with open(path) as f:
        state = json.load(f)
    del state["ident"]
    with open(path, "w") as f:
        json.dump(state, f)
    again = _local(tmp_path / "a")

    assert own_stream(again, APP, V) != original
    assert original.partition("~")[2] in again._local.inherited_owners(APP, V)


def test_a_moved_roots_copy_gets_a_stream_of_its_own(tmp_path):
    original = own_stream(_local(tmp_path / "a"), APP, V)
    shutil.move(str(tmp_path / "a"), str(tmp_path / "b"))
    moved = own_stream(_local(tmp_path / "b"), APP, V)
    shutil.copytree(tmp_path / "b", tmp_path / "copy")

    assert own_stream(_local(tmp_path / "copy"), APP, V) not in (original, moved)


def test_a_record_copy_deleted_and_fetched_again_gets_a_new_stream(tmp_path, monkeypatch):
    with mocked_bucket(monkeypatch):
        monkeypatch.setenv("VMN_WRITER_ID", "gpu07")
        host = cached_host(tmp_path, "a")
        host.save(APP, V, meta(V), {})
        before = own_stream(host, APP, V)

        host._local.delete(APP, V)  # prune --local-only

        assert own_stream(host, APP, V) not in (before, None)
        buffered.close_all()


def test_a_compacted_stream_is_never_appended_to_again(tmp_path):
    storage = _local(tmp_path / "a")
    stream = own_stream(storage, APP, V)
    assert storage.append_metric_block(APP, V, stream, block(1.0))
    assert compact_writer(storage, APP, V, stream)

    assert own_stream(_local(tmp_path / "a"), APP, V) != stream


def test_without_a_local_copy_the_stream_is_the_processes(tmp_path, monkeypatch):
    with mocked_bucket(monkeypatch):
        monkeypatch.setenv("VMN_WRITER_ID", "gpu07")
        remote = s3_storage()

        assert own_stream(remote, APP, V) == own_stream(s3_storage(), APP, V)
        assert own_stream(remote, APP, V).startswith("gpu07~")


def test_each_log_buffer_has_a_stream_of_its_own(tmp_path, monkeypatch):
    with mocked_bucket(monkeypatch):
        monkeypatch.setenv("VMN_WRITER_ID", "gpu07")
        s3_storage().save(APP, V, meta(V), {})
        one, two = BufferedRemoteStorage(s3_storage()), BufferedRemoteStorage(s3_storage())

        assert own_stream(one, APP, V) != own_stream(two, APP, V)
        assert own_stream(one, APP, V) == own_stream(one, APP, V)
        buffered.close_all()


def test_a_tilde_in_an_explicit_writer_id_is_replaced(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "team~gpu07")
    writer._WRITER_ID = None

    assert get_writer_id() == "team-gpu07"


def test_a_tag_lands_in_the_record_copys_stream(tmp_path):
    storage = _local(tmp_path / "a")

    assert tag_run(storage, APP, V, {"k": "v"})

    log_dir = os.path.join(storage.local_record_dir(APP, V), "log")
    assert os.listdir(log_dir) == [f"{own_stream(storage, APP, V)}.jsonl"]


def test_index_caches_from_before_stream_keys_are_dropped():
    from vmn_exp.core.index_store_schema import SCHEMA_VERSION

    assert SCHEMA_VERSION != "exp-index-12"  # metric objects renamed


def test_the_merged_log_names_each_entrys_writer_id_not_its_stream(tmp_path):
    storage = _local(tmp_path / "a")
    stream = own_stream(storage, APP, V)
    storage.append_log_entry(APP, V, stream, {"timestamp": "2026-01-01T00:00:00Z",
                                              "type": "note", "text": "n"})
    assert storage.append_metric_block(APP, V, stream, block(1.0))

    log = storage.load_merged_log(APP, V)

    assert sorted(e["type"] for e in log) == ["metrics", "note"]
    assert {e["_writer"] for e in log} == {"gpu07"}
