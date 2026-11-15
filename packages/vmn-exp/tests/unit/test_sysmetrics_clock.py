"""The system-metrics probe reads and waits on the clock it is handed
(plan 44 G10), so its timing is tested without sleeping."""
import pytest
from fakes.clock import FakeClock
from test_fix_sysmetrics import _FakeProc, _fake_psutil, _use

from vmn_exp.sdk import sysmetrics


class _SleepRecordingClock(FakeClock):
    def __init__(self):
        super().__init__()
        self.sleeps = []

    def sleep(self, sec):
        self.sleeps.append(sec)
        super().sleep(sec)


class _WalkCostingProc(_FakeProc):
    """A root whose tree walk takes *walk_cost* seconds on *clock*."""

    def __init__(self, *args, clock, walk_cost, **kwargs):
        super().__init__(*args, **kwargs)
        self.walks = 0
        self._clock = clock
        self._walk_cost = walk_cost

    def children(self, recursive=True):
        self.walks += 1
        self._clock.advance(self._walk_cost)
        return super().children(recursive)


def test_probe_waits_only_the_remaining_minimum_interval(monkeypatch):
    clock = _SleepRecordingClock()
    _use(monkeypatch, psutil=_fake_psutil(_FakeProc(1, rss_mb=10)))
    collector = sysmetrics.build_collector(1, clock=clock)

    clock.advance(0.03)
    collector()

    assert clock.sleeps == [pytest.approx(sysmetrics.MIN_SAMPLE_INTERVAL_SEC - 0.03)]


def test_tree_walk_is_skipped_until_its_duty_cycle_allows(monkeypatch):
    clock = FakeClock()
    root = _WalkCostingProc(1, rss_mb=10, clock=clock, walk_cost=0.05)
    _use(monkeypatch, psutil=_fake_psutil(root))
    collector = sysmetrics.build_collector(1, clock=clock)
    walks = root.walks  # the walk that primed the probe

    for _ in range(4):  # a walk costing 0.05 s is due again 5 s after it began
        clock.advance(1)
        collector()
    assert root.walks == walks

    clock.advance(1)
    collector()
    assert root.walks == walks + 1


def test_sampler_waits_out_the_priming_interval_on_its_clock(monkeypatch):
    clock = _SleepRecordingClock()
    monkeypatch.setattr(sysmetrics, "build_collector", lambda pid, clock: (lambda: {}))
    sampler = sysmetrics.Sampler(lambda values: None, False, clock=clock)

    sampler._build()  # what the init thread of an enabled sampler runs

    assert clock.sleeps == [sysmetrics.MIN_SAMPLE_INTERVAL_SEC]
