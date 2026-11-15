"""Wall-clock budgets of the ``serial`` timing benchmarks, held on a shared box.

Another suite running at the same time (a parallel worktree, the other
suite) stretches a measurement well past its budget while the code is as
fast as ever. So a step is held to its budget as it would run uncontended:
its wall time less what the box's contention added to the CPU it spent. The
contention is how many times slower than the process's CPU time a busy loop
runs, sampled before and after the step: about 1 on a quiet box, so a
regression there still fails. A step still over budget (a spike) is measured
again, the fastest attempt kept. A step within its budget as measured is not
sampled after, and a retry starts from the sample its last attempt ended on:
each sample is a busy loop of ``SPIN_SEC``.

Only CPU time is stretched by a busy box, so only the CPU the measurement
spent (this process and the children it waited for) is taken to be slowed:
a step that *waits* (on a listing, a lock, a timer) is held to its whole
wall time. And the busy loop is timed against the whole process's CPU, not
its thread's: waiting for the GIL behind another thread of this process is
the code's own cost, not the box's.
"""
import os
import time

ATTEMPTS = 3
# A shorter spin reads too little contention: the scheduler favours a thread
# that just woke, for a while (0.05 s read ~1.1 where a busy box was ~2.5).
SPIN_SEC = 0.5


def contention(wall, cpu, spin_sec):
    """How many times slower than the process's CPU time a busy loop runs now
    (at least 1)."""
    wall_0, cpu_0 = wall(), cpu()
    while cpu() - cpu_0 < spin_sec:
        pass
    return max(1.0, (wall() - wall_0) / (cpu() - cpu_0))


# The real clocks: the bench tests are where they are chosen (the defaults
# of the functions below), :func:`contention` is handed them.
BOX_CLOCKS = {"wall": time.perf_counter, "cpu": time.process_time, "spin_sec": SPIN_SEC}


def box_contention():
    """:func:`contention` of this box, now."""
    return contention(**BOX_CLOCKS)


def cpu_spent():
    """CPU seconds of this process and of the children it has waited for."""
    return sum(os.times()[:4])


def fastest(measure, budget, attempts=ATTEMPTS, contention=box_contention, cpu=cpu_spent):
    """The fewest uncontended seconds *measure()* reported over up to
    *attempts* calls, stopping at the first within *budget*."""
    steps = fastest_each(lambda: {"step": measure()}, {"step": budget}, attempts, contention, cpu)
    return steps["step"]


def fastest_each(measure, budgets, attempts=ATTEMPTS, contention=box_contention, cpu=cpu_spent):
    """``{step: fewest uncontended seconds}`` over up to *attempts* calls of
    *measure()* (each ``{step: seconds}``), stopping once every step is
    within its ``budgets[step]``."""
    def within(best):
        return all(best[step] <= budget for step, budget in budgets.items())

    return fastest_until(measure, within, attempts, contention, cpu)


def fastest_until(measure, within, attempts=ATTEMPTS, contention=box_contention, cpu=cpu_spent):
    """``{step: fewest uncontended seconds}`` over up to *attempts* calls of
    *measure()* (each ``{step: seconds}``), stopping once ``within(best)``:
    for a budget bounding several steps together (one step's time minus
    another's)."""
    best, sample = None, contention()
    for _ in range(max(attempts, 1)):
        before, cpu_0 = sample, cpu()
        took = measure()
        spent = cpu() - cpu_0
        if within(_fewest(best, took)):
            return _fewest(best, took)
        sample = contention()
        best = _fewest(best, _uncontended(took, spent, (before + sample) / 2))
        if within(best):
            break
    return best


def _fewest(best, took):
    return took if best is None else {step: min(seconds, best[step])
                                      for step, seconds in took.items()}


def _uncontended(took, spent, slowdown):
    # A step spent at most its wall time over the slowdown on the CPU, and
    # no more than the whole measurement did.
    return {step: seconds - min(seconds / slowdown, spent) * (slowdown - 1)
            for step, seconds in took.items()}
