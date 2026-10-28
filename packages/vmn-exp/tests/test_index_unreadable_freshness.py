"""An index's freshness says how many records it set aside unread
(``unreadable: {count, store_errors, last_error}``, absent when none): a store
throttling every read used to fail the refresh, which the dashboard showed;
setting the records aside made the refresh succeed, so without it a
throttled store's stale or missing runs looked fresh."""
import glob
import os

from s3_helpers import meta
from test_index_metric_reads_s3 import APP, V, _index, s3  # noqa: F401
from test_index_store_throttled import throttled  # noqa: F401
import vmn_exp.core.index as index_module
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

W = "1.0.0-dev.w"


def test_no_unreadable_record_leaves_freshness_without_it(s3, tmp_path):
    index = _index(tmp_path).refresh()
    assert "unreadable" not in index.freshness()


def test_throttled_records_are_counted_as_store_errors(s3, tmp_path, throttled):  # noqa: F811
    s3.save(APP, W, meta(W), {})
    throttled.update({V, W})
    index = _index(tmp_path).refresh()

    unreadable = index.freshness()["unreadable"]

    assert unreadable["count"] == 2 and unreadable["store_errors"] == 2
    assert "SlowDown" in unreadable["last_error"]


def test_a_records_own_failure_is_not_a_store_error(s3, tmp_path, monkeypatch):
    real = index_module.refresh_record

    def refresh_record(key, *args, **kwargs):
        if key == V:
            raise TypeError("'NoneType' object is not subscriptable")
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    index = _index(tmp_path).refresh()

    assert index.freshness()["unreadable"] == {
        "count": 1, "store_errors": 0,
        "last_error": "TypeError(\"'NoneType' object is not subscriptable\")"}


def test_a_long_error_is_cut_short(s3, tmp_path, monkeypatch):
    def refresh_record(key, *args, **kwargs):
        raise ValueError("x" * 500)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    index = _index(tmp_path).refresh()

    assert len(index.freshness()["unreadable"]["last_error"]) <= 200


def test_records_read_on_retry_leave_the_count(s3, tmp_path, throttled, monkeypatch):  # noqa: F811
    throttled.add(V)
    index = _index(tmp_path).refresh()
    throttled.clear()
    monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 0)

    index.refresh()

    assert "unreadable" not in index.freshness()


def test_a_set_aside_record_deleted_from_the_store_leaves_the_count(
        s3, tmp_path, throttled, monkeypatch):  # noqa: F811
    s3.save(APP, W, meta(W), {})
    index = _index(tmp_path).refresh()  # W known
    s3.save(APP, "1.0.0-dev.n", meta("1.0.0-dev.n"), {})
    throttled.update({W, "1.0.0-dev.n"})
    s3.save_file(APP, W, "run_state.yml", "state: running\nexit_code: null\n")
    index.refresh()
    assert index.freshness()["unreadable"]["count"] == 2

    for verstr in (W, "1.0.0-dev.n"):
        s3.delete(APP, verstr)
    monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 0)
    index.refresh()

    assert "unreadable" not in index.freshness()


def _local_with_a_broken_record(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    for verstr in ("0.0.1-dev.a", "0.0.1-dev.b"):
        st.save(APP, verstr, {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, {})
    broken, = glob.glob(os.path.join(str(tmp_path / "store"), "**", "0.0.1-dev.b", "metadata.yml"),
                        recursive=True)
    os.chmod(broken, 0)
    return st


def test_a_local_index_counts_a_record_it_could_not_read(tmp_path):
    st = _local_with_a_broken_record(tmp_path)
    index = ExperimentIndex(st, APP, cache_path=str(tmp_path / "i.sqlite")).refresh()
    assert index.freshness()["unreadable"]["count"] == 1


def test_the_io_helpers_unreadable_records_are_counted(tmp_path):
    """The helper process reads the records: its set-aside ones are the
    count, not the server process's (which reads none)."""
    st = _local_with_a_broken_record(tmp_path)
    index = ExperimentIndex(st, APP, cache_path=str(tmp_path / "i.sqlite"))
    assert index.use_io_process()
    try:
        index.refresh()
        assert index.freshness()["unreadable"]["count"] == 1
    finally:
        index.close()
