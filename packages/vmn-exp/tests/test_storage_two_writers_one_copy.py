"""What the real local storage does with two writer ids on one record copy,
the arrangement an adopted run rests on (plan 38 A5): the supervisor's
``<host>`` and its child's ``<host>-sdk``."""
from s3_helpers import meta

from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.streams import guest_writer_id, owner_of
from vmn_exp.core.writer import append_metric_entries, create_log_entry, own_stream
from vmn_exp.storage.local import LocalSnapshotStorage

APP, V = "app", "1.0.0-dev.abc.r1"
HOST, GUEST = "host", guest_writer_id("host")


def _copy(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), "runs")
    storage.save(APP, V, meta(V), {})
    return storage


def _log(storage, writer, value):
    entry = create_log_entry("metrics", values={"loss": value})
    entry["step"] = 0
    assert append_metric_entries(storage, APP, V, [entry], writer=writer)


def test_two_writer_ids_on_one_copy_share_the_owner_and_get_separate_files(tmp_path):
    storage = _copy(tmp_path)
    host, guest = own_stream(storage, APP, V, HOST), own_stream(storage, APP, V, GUEST)

    _log(storage, HOST, 1.0)
    _log(storage, GUEST, 0.5)

    assert owner_of(host) == owner_of(guest)
    assert host != guest
    assert {host, guest} <= set(storage.metric_objects(APP, V))


def test_compacting_one_writers_stream_moves_both_writers_to_a_new_owner(tmp_path):
    storage = _copy(tmp_path)
    _log(storage, HOST, 1.0)
    _log(storage, GUEST, 0.5)
    before = own_stream(storage, APP, V, HOST)

    assert compact_writer(storage, APP, V, own_stream(storage, APP, V, GUEST))

    after_host, after_guest = own_stream(storage, APP, V, HOST), own_stream(storage, APP, V, GUEST)
    assert owner_of(after_host) == owner_of(after_guest) != owner_of(before)
