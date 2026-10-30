"""A heartbeat whose previous write was its own skips the read before it.

Each beat used to GET ``run_state.yml`` (to drop a duplicate attempt's beats
once another attempt finished the run) and then PUT it. Now a beat PUTs under
``If-Match`` on the ETag of its own last write: the PUT lands only while
nobody else wrote the file, so the read is needed only when it is refused —
and that read still stops a beaten attempt.
"""
import time

import pytest
import yaml
from s3_helpers import meta, mocked_bucket, record_calls, s3_storage

from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.sdk.state_publisher import RunStatePublisher

APP = "app"
X = "0.0.1-dev.abc1234.0000001"
BEATS = 6


@pytest.fixture
def storage(monkeypatch):
    with mocked_bucket(monkeypatch):
        store = s3_storage()
        assert store.create_exclusive(APP, X, meta(X), {})
        yield store


def _state(seq, attempt="mine", **extra):
    return dict({"state": "running", "attempt": attempt, "heartbeat_seq": seq,
                 "exit_code": None}, **extra)


def _stored():
    return load_run_state(s3_storage(), APP, X) or {}


def _until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def _beat(publisher, seq, **extra):
    publisher.publish(_state(seq, **extra), heartbeat=True)
    _until(lambda: _stored().get("heartbeat_seq") == seq or publisher.superseded)


def _state_calls(calls, op):
    return [p for o, p in calls if o == op and p["Key"].endswith(RUN_STATE_FILE)]


def test_beats_after_our_own_write_skip_the_read(storage):
    calls = record_calls(storage._s3)
    publisher = RunStatePublisher(storage, APP, X)
    publisher.publish(_state(0))
    _until(lambda: _stored().get("heartbeat_seq") == 0)
    for seq in range(1, BEATS + 1):
        _beat(publisher, seq)
    assert publisher.close(10)

    puts = _state_calls(calls, "PutObject")
    gets = _state_calls(calls, "GetObject")
    assert len(puts) == BEATS + 1
    # Beats used to read before every write: 2 * BEATS requests, not BEATS.
    # The one read is the first write's guard (no other attempt finished it).
    assert len(gets) == 1
    assert sum("IfMatch" in p for p in puts) == BEATS


def test_a_refused_beat_reads_and_stops_when_another_attempt_finished(storage):
    publisher = RunStatePublisher(storage, APP, X)
    publisher.publish(_state(0))
    for seq in (1, 2):
        _beat(publisher, seq)
    final = {"state": "finished", "attempt": "other", "exit_code": 0}
    s3_storage().save_file(APP, X, RUN_STATE_FILE, yaml.dump(final))

    _beat(publisher, 3)
    assert publisher.close(10)
    assert publisher.superseded
    assert _stored() == final


def test_a_refused_beat_writes_after_reading_a_live_state(storage):
    publisher = RunStatePublisher(storage, APP, X)
    publisher.publish(_state(0))
    for seq in (1, 2):
        _beat(publisher, seq)
    s3_storage().save_file(APP, X, RUN_STATE_FILE, yaml.dump(_state(99, attempt="other")))

    calls = record_calls(storage._s3)
    _beat(publisher, 3)
    _beat(publisher, 4)
    assert publisher.close(10)
    assert not publisher.superseded
    assert _stored()["heartbeat_seq"] == 4
    # The refused beat read once; the beat after it is conditional again.
    assert len(_state_calls(calls, "GetObject")) == 1
