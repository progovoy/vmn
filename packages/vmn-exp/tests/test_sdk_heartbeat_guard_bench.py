"""Guarding every heartbeat must not slow it down (user: "as long as it will
not kill performance").

A local beat used to read and parse the stored state, then write it
unconditionally. Guarded, it is one conditional write under the record's
state lock on the token of its own last write (one read, no parse). Timed
against that old read-then-write on the same disk, in interleaved rounds
(the fastest of each counts), so the bound holds on any machine and under
noise. Timed, so serial.
"""
import time

import pytest
import yaml
from s3_helpers import meta

from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.sdk.state_publisher import RunStatePublisher
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
X = "0.0.1-dev.abc1234.0000001"
Y = "0.0.1-dev.abc1234.0000002"
BEATS = 2_000
ROUNDS = 5
# The guarded beat may cost at most this much more than the unguarded one.
BOUND = 1.5


@pytest.fixture
def local(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "s"), "runs")
    for verstr in (X, Y):
        st.save(APP, verstr, meta(verstr), {})
    return st


def _state(seq):
    return {"state": "running", "attempt": "mine", "host": "h", "pid": 1,
            "command": ["python", "train.py"], "started_at": "2026-01-01T00:00:00Z",
            "heartbeat": "2026-01-01T00:00:00Z", "heartbeat_seq": seq,
            "heartbeat_interval_sec": 30, "exit_code": None, "finished_at": None,
            "duration_sec": None}


def _per_beat(beats):
    """Each of *beats*' fastest per-beat time over interleaved rounds; each
    beat is called with its run's next heartbeat_seq, BEATS in all."""
    per_round = BEATS // ROUNDS
    best = [float("inf")] * len(beats)
    for start in range(1, BEATS + 1, per_round):
        for i, beat in enumerate(beats):
            started = time.perf_counter()
            for seq in range(start, start + per_round):
                beat(seq)
            best[i] = min(best[i], (time.perf_counter() - started) / per_round)
    return best


def _unguarded(local):
    """The old local beat: read and parse the stored state, then write."""
    def beat(seq):
        load_run_state(local, APP, Y)
        local.save_file(APP, Y, RUN_STATE_FILE, yaml.dump(_state(seq), sort_keys=False))
    return beat


@pytest.mark.serial
def test_a_guarded_local_beat_costs_about_what_an_unguarded_one_did(local):
    publisher = RunStatePublisher(local, APP, X)
    publisher.publish(_state(0))
    local.save_file(APP, Y, RUN_STATE_FILE, yaml.dump(_state(0)))

    guarded, unguarded = _per_beat(
        [lambda seq: publisher.publish(_state(seq), heartbeat=True), _unguarded(local)])

    print(f"\n{BEATS} local beats: guarded {guarded * 1e6:.0f}us/beat, "
          f"unguarded {unguarded * 1e6:.0f}us/beat ({guarded / unguarded:.2f}x)")
    assert load_run_state(local, APP, X)["heartbeat_seq"] == BEATS
    assert guarded <= BOUND * unguarded
