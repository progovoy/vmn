"""Run status is derived at the time the caller gives (plan 44 G11): a
running run turns stuck once the given ``now`` passes its stale window,
durations run to it, and a writer clock ahead of it proves nothing."""
from datetime import timedelta

import pytest
from fakes.clock import FakeClock
from vmn_exp.core.status import (
    RUNNING,
    STUCK,
    derive_status,
    last_alive_at,
    stale_after_sec,
    status_fields,
)


def _iso(when):
    return when.isoformat()


def _running(started, beat=None):
    return {"state": "running", "exit_code": None, "started_at": _iso(started),
            "heartbeat": _iso(beat or started), "heartbeat_interval_sec": 10}


def test_running_becomes_stuck_when_the_given_now_passes_the_stale_window():
    clock = FakeClock()
    state = _running(clock.now())
    window = stale_after_sec(state)

    clock.advance(window)
    assert derive_status(state, now=clock.now()) == RUNNING

    clock.advance(1)
    assert derive_status(state, now=clock.now()) == STUCK


def test_status_fields_uses_the_given_now_for_durations():
    clock = FakeClock()
    state = _running(clock.now())

    clock.advance(5)
    fields = status_fields(state, now=clock.now())

    assert fields["status"] == RUNNING
    assert fields["duration_sec"] == 5
    assert fields["stale_sec"] == 5


def test_last_alive_at_ignores_a_writer_time_after_the_given_now():
    clock = FakeClock()
    observed = clock.now()
    state = _running(observed, beat=observed + timedelta(seconds=100))

    assert last_alive_at(state, clock.now() + timedelta(seconds=50), observed) == observed
    assert (last_alive_at(state, clock.now() + timedelta(seconds=200), observed)
            == observed + timedelta(seconds=100))


def test_derive_status_without_now_is_a_type_error():
    state = _running(FakeClock().now())
    with pytest.raises(TypeError):
        derive_status(state)
    with pytest.raises(TypeError):
        status_fields(state)
    with pytest.raises(TypeError):
        last_alive_at(state)
