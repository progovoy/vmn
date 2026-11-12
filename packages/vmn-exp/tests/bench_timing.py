"""Wall-clock budgets of the ``serial`` timing benchmarks, held on a shared box.

Another suite running at the same time (a parallel worktree, the other
suite) stretches a measurement well past its budget while the code is as
fast as ever. So a step's wall time is divided by the box's contention when
it ran — how many times slower than its CPU time a busy loop runs then,
sampled before and after the step — and held to its budget as it would run
uncontended: about 1 on a quiet box, so a regression there still fails. A
step still over budget (a spike) is measured again, the fastest attempt
kept. Wall clock, not CPU time, for the step itself: some benchmarks guard
that a step does not *wait* (on a listing, a lock), which CPU time misses.
"""
import time

ATTEMPTS = 3
# A shorter spin reads too little contention: the scheduler favours a thread
# that just woke, for a while (0.05 s read ~1.1 where a busy box was ~2.5).
SPIN_SEC = 0.5


def contention(wall=time.perf_counter, cpu=time.thread_time, spin_sec=SPIN_SEC):
    """How many times slower than its CPU time a busy loop runs now (at least 1)."""
    wall_0, cpu_0 = wall(), cpu()
    while cpu() - cpu_0 < spin_sec:
        pass
    return max(1.0, (wall() - wall_0) / (cpu() - cpu_0))


def fastest(measure, budget, attempts=ATTEMPTS, contention=contention):
    """The fewest uncontended seconds *measure()* reported over up to
    *attempts* calls, stopping at the first within *budget*."""
    steps = fastest_each(lambda: {"step": measure()}, {"step": budget}, attempts, contention)
    return steps["step"]


def fastest_each(measure, budgets, attempts=ATTEMPTS, contention=contention):
    """``{step: fewest uncontended seconds}`` over up to *attempts* calls of
    *measure()* (each ``{step: seconds}``), stopping once every step is
    within its ``budgets[step]``."""
    best = _uncontended(measure, contention)
    for _ in range(attempts - 1):
        if all(best[step] <= budget for step, budget in budgets.items()):
            break
        best = {step: min(seconds, best[step])
                for step, seconds in _uncontended(measure, contention).items()}
    return best


def _uncontended(measure, contention):
    before = contention()
    took = measure()
    slowdown = (before + contention()) / 2
    return {step: seconds / slowdown for step, seconds in took.items()}
