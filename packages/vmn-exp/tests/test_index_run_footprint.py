"""A run's memory on a warm ``vmn-exp ui`` server stays within a budget.

A client's server held ~62 KB per run of an app of 486k runs (30 GB) right
after a restart, most of it the ``sys_*`` system metrics (sampled by default)
and their summaries, and repeated tag values decoded once per run. Sensible
defaults must not make 500k runs cost 30 GB: see :mod:`index_footprint` for
the runs measured.
"""
from index_footprint import footprint, report, warm_server

RUNS = 200
BUDGET_PER_RUN = 16_000  # bytes


def test_a_warm_run_fits_the_budget(tmp_path):
    index, snap, cache = warm_server(tmp_path, RUNS)
    try:
        parts = footprint(index, snap, cache, RUNS)
    finally:
        index.close()
    print("\n" + report(parts))
    assert sum(parts.values()) <= BUDGET_PER_RUN, report(parts)
