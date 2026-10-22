"""A journaled sweep re-lists a live run the journal did not name at its own
heartbeat cadence: often enough that a run still beating never reads
``stuck``, rarely enough that watching many long runs costs few listings."""
import datetime
import glob
import os

import pytest

from test_index_journal_hint import _journaled, _make, _reset, clock, spy, st  # noqa: F401
from vmn_exp.core import index_sweep, status

APP = "app"
TICK = 1


def _running(interval):
    return f"state: running\nheartbeat_interval_sec: {interval}\n"


def _gaps(index, spy, clock, live, span):
    """The seconds between the ticks that listed *live* over *span* seconds."""
    listed = []
    for _ in range(span):
        _reset(spy)
        clock.now += TICK
        index.refresh()
        if {live} in spy["list_files"]:
            listed.append(clock.now)
    return {round(b - a) for a, b in zip(listed, listed[1:])}


def test_a_default_heartbeat_run_is_relisted_every_30_seconds_not_10(st, spy, clock):
    live = _make(st, 1, _running(30))
    index = _journaled(st).refresh()
    assert _gaps(index, spy, clock, live, 100) == {30}


def test_a_short_interval_run_is_relisted_at_the_floor(st, spy, clock):
    live = _make(st, 1, _running(5))
    index = _journaled(st).refresh()
    assert _gaps(index, spy, clock, live, 40) == {index_sweep.LIVE_RELIST_SEC}


def test_a_long_interval_run_is_relisted_at_its_interval(st, spy, clock):
    # 600 s beats go stuck after 1800 s: listing at the cadence the run
    # writes at sees every beat, well inside half that window.
    live = _make(st, 1, _running(600))
    index = _journaled(st).refresh()
    assert _gaps(index, spy, clock, live, 1900) == {600}


def test_a_tight_stale_window_caps_the_period_below_the_floor(st, spy, clock, monkeypatch):
    # floor 1 s: a 2 s heartbeat goes stuck after 6 s, so it is listed every 3 s.
    monkeypatch.setenv(status.MIN_STALE_ENV, "1")
    live = _make(st, 1, _running(2))
    index = _journaled(st).refresh()
    assert _gaps(index, spy, clock, live, 12) == {3}


def test_an_unknown_interval_takes_the_status_default(st, spy, clock):
    live = _make(st, 1, "state: running\nheartbeat_interval_sec: soon\n")
    index = _journaled(st).refresh()
    assert _gaps(index, spy, clock, live, 100) == {int(status.DEFAULT_HEARTBEAT_INTERVAL_SEC)}


class Wall:
    """A wall clock that follows the test's monotonic clock."""

    def __init__(self, clock):
        self.clock, self.base = clock, datetime.datetime.now(datetime.timezone.utc)

    def __call__(self, now=None):
        return now or self.base + datetime.timedelta(seconds=self.clock.now - 1000.0)


@pytest.fixture
def wall(clock, monkeypatch):
    w = Wall(clock)
    monkeypatch.setattr(status, "_now", w)
    return w


def _beat(st, verstr, interval, wall):
    now = wall()
    beat = now.isoformat().replace("+00:00", "Z")
    st.save_file(APP, verstr, "run_state.yml",
                 f"{_running(interval)}heartbeat: '{beat}'\n")
    (path,) = glob.glob(os.path.join(st.root, "**", verstr, "run_state.yml"), recursive=True)
    os.utime(path, (now.timestamp(), now.timestamp()))


@pytest.mark.parametrize("interval", [5, 30, 600])
def test_a_beating_run_never_reads_stuck_and_a_silent_one_soon_does(st, spy, clock, wall,
                                                                    interval):
    live = _make(st, 1, None)
    _beat(st, live, interval, wall)
    index = _journaled(st).refresh()
    window = status.stale_after_sec({"heartbeat_interval_sec": interval})
    for offset in range(1, int(3 * window) + 1, TICK):
        clock.now += TICK
        if offset % interval == 0:
            _beat(st, live, interval, wall)
        index.refresh()
        assert index.snapshot().status_of(live) == status.RUNNING, offset

    for offset in range(1, int(window) + TICK + 1, TICK):
        clock.now += TICK
        index.refresh()
    assert index.snapshot().status_of(live) == status.STUCK
