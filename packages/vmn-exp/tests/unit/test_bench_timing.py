"""bench_timing: a timing benchmark's step is held to its budget as it would
run on an uncontended box (its wall time over how much slower than its CPU
time a busy loop runs now), measured again only while over budget, the
fastest attempt kept."""
import time

import pytest
from bench_timing import (BOX_CLOCKS, active_coverage, contention, fastest, fastest_each,
                          fastest_until, untraced)

QUIET = lambda: 1.0  # noqa: E731


def _measures(*seconds):
    taken = list(seconds)
    calls = []

    def measure():
        calls.append(None)
        return taken.pop(0)

    return measure, calls


def test_a_step_within_budget_is_measured_once():
    measure, calls = _measures(0.4, 9.0)
    assert fastest(measure, budget=1.0, contention=QUIET) == 0.4
    assert len(calls) == 1


def test_a_slow_attempt_is_measured_again_until_one_fits():
    measure, calls = _measures(2.1, 0.7, 9.0)
    assert fastest(measure, budget=1.0, contention=QUIET) == 0.7
    assert len(calls) == 2


def test_a_step_slow_on_every_attempt_answers_its_fastest():
    measure, calls = _measures(2.1, 1.8, 2.4)
    assert fastest(measure, budget=1.0, attempts=3, contention=QUIET) == 1.8
    assert len(calls) == 3


def test_steps_with_their_own_budgets_keep_each_ones_fastest():
    attempts = [{"a": 0.2, "b": 3.0}, {"a": 0.5, "b": 0.9}, {"a": 9.0, "b": 9.0}]
    calls = []

    def measure():
        calls.append(None)
        return attempts.pop(0)

    assert fastest_each(measure, {"a": 1.0, "b": 1.0}, contention=QUIET) == {"a": 0.2, "b": 0.9}
    assert len(calls) == 2



def test_steps_bounded_together_are_measured_again_until_their_best_fits():
    attempts = [{"a": 0.9, "b": 0.1}, {"a": 0.7, "b": 0.2}, {"a": 0.4, "b": 0.1}, {"a": 0.1, "b": 0.0}]
    calls = []

    def measure():
        calls.append(None)
        return attempts.pop(0)

    best = fastest_until(measure, lambda b: b["a"] - b["b"] <= 0.4, contention=QUIET)
    assert best == {"a": 0.4, "b": 0.1}
    assert len(calls) == 3

def _cpu_spent(by_the_step):
    """A CPU clock the step moves on by *by_the_step* seconds."""
    readings = iter([10.0, 10.0 + by_the_step])
    return lambda: next(readings)


def test_a_step_slowed_by_other_processes_is_held_to_its_uncontended_time():
    measure, calls = _measures(2.4)
    shared = iter([2.0, 4.0])  # the CPUs given to this process: half, then a quarter
    took = fastest(measure, budget=1.0, contention=lambda: next(shared), cpu=_cpu_spent(0.8))
    assert took == pytest.approx(0.8)
    assert len(calls) == 1


def test_a_step_that_only_waited_is_held_to_its_whole_wall_time():
    """A wait (a lock, a timer, a slow listing) is no shorter on a quiet box."""
    measure, _ = _measures(2.4)
    took = fastest(measure, budget=1.0, attempts=1, contention=lambda: 2.0, cpu=_cpu_spent(0.0))
    assert took == pytest.approx(2.4)


def test_only_the_cpu_a_step_spent_is_held_to_be_slowed():
    """0.5 s of CPU at half speed took 1 s: the other 1.4 s were waiting."""
    measure, _ = _measures(2.4)
    took = fastest(measure, budget=1.0, attempts=1, contention=lambda: 2.0, cpu=_cpu_spent(0.5))
    assert took == pytest.approx(1.9)


def test_the_boxs_contention_is_read_on_the_whole_processs_cpu_time():
    """Not the thread's: waiting for the GIL behind another thread of this
    process is the code's own cost, not the box's."""
    assert BOX_CLOCKS["cpu"] is time.process_time


def test_contention_is_handed_its_clocks():
    with pytest.raises(TypeError):
        contention()


def _sampled():
    """A quiet box's contention, and the samples taken of it."""
    samples = []

    def contention():
        samples.append(None)
        return 1.0

    return contention, samples


def test_a_step_within_budget_as_measured_is_not_sampled_again():
    """Its wall time is already within: no second busy loop to hold it lower."""
    measure, _ = _measures(0.4)
    contention, samples = _sampled()
    assert fastest(measure, budget=1.0, contention=contention) == 0.4
    assert len(samples) == 1


def test_a_retried_step_starts_from_the_sample_its_last_attempt_ended_on():
    measure, _ = _measures(2.1, 0.7)
    contention, samples = _sampled()
    assert fastest(measure, budget=1.0, contention=contention) == 0.7
    assert len(samples) == 2


class _Clocks:
    """A wall clock running *slowdown* times faster than the thread's CPU clock."""

    def __init__(self, slowdown):
        self.slowdown, self.cpu_sec = slowdown, 0.0

    def cpu(self):
        self.cpu_sec += 0.001
        return self.cpu_sec

    def wall(self):
        return self.cpu_sec * self.slowdown


def test_contention_is_a_busy_loops_wall_time_over_its_cpu_time():
    clocks = _Clocks(slowdown=3.0)
    assert round(contention(wall=clocks.wall, cpu=clocks.cpu, spin_sec=0.01), 6) == 3.0


def test_contention_is_never_below_one():
    clocks = _Clocks(slowdown=0.5)
    assert contention(wall=clocks.wall, cpu=clocks.cpu, spin_sec=0.01) == 1.0


class _Tracer:
    """A tracer controller recording when it stops and starts around the step."""

    def __init__(self, events):
        self.events = events

    def stop(self):
        self.events.append("stop")

    def start(self):
        self.events.append("start")


def test_a_step_runs_with_the_tracer_stopped_and_restarted_after():
    events = []
    took = untraced(lambda: events.append("step") or 0.4, _Tracer(events))
    assert took == 0.4
    assert events == ["stop", "step", "start"]


def test_a_step_that_raises_restarts_the_tracer():
    events = []

    def step():
        events.append("step")
        raise ValueError("boom")

    with pytest.raises(ValueError):
        untraced(step, _Tracer(events))
    assert events == ["stop", "step", "start"]


def test_without_a_tracer_the_step_just_runs():
    assert untraced(lambda: 0.4, None) == 0.4


def test_every_attempt_is_measured_with_the_tracer_stopped():
    events = []
    taken = [2.1, 0.7]

    def measure():
        events.append("step")
        return taken.pop(0)

    assert fastest(measure, budget=1.0, contention=QUIET, tracer=lambda: _Tracer(events)) == 0.7
    assert events == ["stop", "step", "start"] * 2


def test_without_coverage_running_fastest_just_measures():
    measure, calls = _measures(0.4)
    assert fastest(measure, budget=1.0, contention=QUIET, tracer=lambda: None) == 0.4
    assert len(calls) == 1


def test_the_benches_pause_the_coverage_tracing_this_process():
    import coverage
    assert active_coverage() is coverage.Coverage.current()
