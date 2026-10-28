"""A record read the store refuses (S3 ``SlowDown`` past botocore's retries)
never fails the refresh: the record is set aside and read afresh later, like
any unreadable record. One throttled GET used to fail the whole refresh,
dropping the reads of the records around it, and the sweep's reset made the
next refresh re-list the whole store — more of the requests the store was
refusing, a second later, every time ("The background refresh has not
completed ... SlowDown")."""
import logging

import pytest
from botocore.exceptions import ClientError
from s3_helpers import meta
from test_index_metric_reads_s3 import APP, V, _index, s3  # noqa: F401
import vmn_exp.core.index as index_module

W = "1.0.0-dev.w"
DONE = "state: succeeded\nexit_code: 0\n"


def _slow_down():
    return ClientError({"Error": {"Code": "SlowDown", "Message": "Please reduce your request rate."}},
                       "GetObject")


@pytest.fixture
def throttled(monkeypatch):
    """The keys whose reads the store refuses."""
    keys = set()
    real = index_module.refresh_record

    def refresh_record(key, *args, **kwargs):
        if key in keys:
            raise _slow_down()
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    return keys


def _statuses(index):
    snapshot = index.refresh().snapshot()
    return {r["verstr"]: snapshot.status_of(r["verstr"]) for r in snapshot.rows}


def test_a_throttled_new_record_is_set_aside_and_read_later(s3, tmp_path, throttled, monkeypatch):
    s3.save(APP, W, meta(W), {})
    throttled.add(W)
    index = _index(tmp_path)

    assert list(_statuses(index)) == [V]  # no exception

    throttled.clear()
    monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 0)
    assert sorted(_statuses(index)) == sorted([V, W])


def test_a_throttled_read_keeps_the_other_records_of_its_refresh(s3, tmp_path, throttled):
    s3.save(APP, W, meta(W), {})
    s3.save_file(APP, W, "run_state.yml", "state: running\nexit_code: null\n")
    index = _index(tmp_path)
    assert _statuses(index) == {V: "running", W: "running"}
    for verstr in (V, W):
        s3.save_file(APP, verstr, "run_state.yml", DONE)
    throttled.add(W)

    assert _statuses(index) == {V: "succeeded", W: "running"}


def test_many_throttled_records_are_warned_about_once(s3, tmp_path, throttled, caplog):
    for n in range(5):
        verstr = f"1.0.0-dev.t{n}"
        s3.save(APP, verstr, meta(verstr), {})
        throttled.add(verstr)
    index = _index(tmp_path)

    with caplog.at_level(logging.WARNING, logger="vmn_exp.core.index"):
        index.refresh()
        index.refresh()

    warnings = [r for r in caplog.records if r.name == "vmn_exp.core.index"]
    assert len(warnings) == 1
    assert "SlowDown" in warnings[0].getMessage()


def test_a_set_aside_record_is_not_read_before_its_retry_is_due(s3, tmp_path, monkeypatch):
    """A live run is listed every heartbeat: each listing re-reading the
    whole set-aside record would be hundreds of GETs to a refusing store."""
    reads, real = [], index_module.refresh_record
    throttled = [True]

    def refresh_record(key, *args, **kwargs):
        reads.append(key)
        if throttled[0]:
            raise _slow_down()
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    index = _index(tmp_path)
    index.refresh()
    throttled[0] = False
    s3.save_file(APP, V, "run_state.yml", DONE)

    assert _statuses(index) == {}
    assert reads == [V]

    monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 0)
    assert _statuses(index) == {V: "succeeded"}


def test_a_cold_load_ends_when_a_cut_record_is_set_aside(s3, tmp_path, throttled):
    """A remote cold load reads a new record's row files first and puts the
    rest of its log off (index_rows_first); a record whose first part was
    set aside was cut and put off again, forever."""
    import threading

    from test_index_metric_reads_s3 import _log_segment

    for seq in range(3):
        _log_segment(s3, seq)
    throttled.add(V)
    index = _index(tmp_path)
    loaded = threading.Thread(target=index.refresh, daemon=True)

    loaded.start()
    loaded.join(20)

    assert not loaded.is_alive()
    assert index.snapshot().rows == ()
