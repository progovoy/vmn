"""The supervision loop wakes when the child exits (plan 39 B9b).

Unit tests on fakes: the clock only moves when the fake child wait says so.
"""
import subprocess

from vmn_exp.cli.supervise_loop import popen_waiter, watch


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeChild:
    """A child that exits at *exits_at*; waiting on it advances *clock*."""

    def __init__(self, clock, exits_at):
        self.clock = clock
        self.exits_at = exits_at
        self.waits = []

    def exited(self):
        return self.clock.now >= self.exits_at

    def wait(self, timeout):
        self.waits.append(timeout)
        self.clock.now = min(self.clock.now + timeout, self.exits_at)
        return self.exited()


def _watch(clock, child, ticks, interval=0.5):
    watch(child.exited, child.wait, ticks.append, clock, interval)


def test_the_loop_returns_at_the_childs_exit_time_not_the_next_interval():
    clock = FakeClock()
    child = FakeChild(clock, exits_at=0.3)

    _watch(clock, child, [])

    assert clock.now == 0.3


def test_tick_runs_once_per_interval_while_the_child_lives():
    clock = FakeClock()
    ticks = []

    _watch(clock, FakeChild(clock, exits_at=1.7), ticks)

    assert len(ticks) == 4


def test_a_child_that_has_already_exited_gets_no_wait():
    clock = FakeClock()
    child = FakeChild(clock, exits_at=0.0)
    ticks = []

    _watch(clock, child, ticks)

    assert child.waits == []
    assert ticks == []


def test_tick_receives_the_injected_clocks_time():
    clock = FakeClock()
    clock.now = 100.0
    ticks = []

    _watch(clock, FakeChild(clock, exits_at=101.2), ticks)

    assert ticks == [100.0, 100.5, 101.0]


def test_no_wait_is_requested_after_the_child_has_exited():
    clock = FakeClock()
    child = FakeChild(clock, exits_at=0.7)

    _watch(clock, child, [])

    assert child.waits == [0.5, 0.5]


class FakePopen:
    def __init__(self, exits):
        self.exits = exits
        self.timeouts = []

    def wait(self, timeout):
        self.timeouts.append(timeout)
        if not self.exits:
            raise subprocess.TimeoutExpired("cmd", timeout)
        return 0


def test_popen_waiter_reports_a_wait_that_times_out_as_still_running():
    proc = FakePopen(exits=False)

    assert popen_waiter(proc)(0.5) is False
    assert proc.timeouts == [0.5]


def test_popen_waiter_reports_an_exited_child():
    assert popen_waiter(FakePopen(exits=True))(0.5) is True
