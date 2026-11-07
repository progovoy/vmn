"""Plan 31 §2 bench: 45 trainings x 16 dates x 1000 trials. Once warm, the
Outer runs rows' ``rolled`` (median of the date bests, and of the dates'
own value found by ``params.trade_date``) answers a new index generation
of a few changed trials in under ~20 ms. Timed, so serial."""
import time

import pytest
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row
from vmn_exp.ui.job_aggregate import JobAgg
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

TRAININGS, DATES, TRIALS = 45, 16, 1000
SCHEMA = {"best_value": {"goal": "max", "primary": True}, "date.best_value": {"goal": "max"}}
AGGS = [JobAgg("median"), JobAgg("median", "field:params.trade_date", "own", "date.best_value")]
DONE = {"state": "finished", "exit_code": 0}


def _row(i, verstr, parent, params, values):
    meta = {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z", "branch": "main"}
    if parent:
        meta["parent"] = parent
    log = [{"timestamp": "t", "type": "create", "params": params},
           {"timestamp": "t", "type": "metrics", "values": values}]
    return experiment_row(i + 1, meta, log)


class Board:
    def __init__(self):
        self.rows, self.generation = [], 0
        for t in range(TRAININGS):
            training = f"1.0.0-dev.t{t:03d}"
            self._add(training, None, {}, {})
            for d in range(DATES):
                date = f"{training}.d{d:02d}"
                self._add(date, training, {"trade_date": f"2024-{d + 1:02d}"},
                          {"date.best_value": (t * d % 97) / 97})
                for k in range(TRIALS):
                    self._add(f"{date}.k{k:04d}", date, {},
                              {"best_value": ((t + d * 31 + k * 17) % 1009) / 1009})

    def _add(self, verstr, parent, params, values):
        self.rows.append(_row(len(self.rows), verstr, parent, params, values))

    def improve(self, count):
        for n in range(count):
            i = len(self.rows) - 1 - n * 977
            row = self.rows[i]
            self.rows[i] = dict(row, metrics=dict(row["metrics"], best_value=2.0 + n))

    def snapshot(self):
        self.generation += 1
        states = dict.fromkeys((row["verstr"] for row in self.rows), DONE)
        return IndexSnapshot.build("app", self.generation, list(self.rows), states)


@pytest.mark.serial
def test_rolled_answers_a_new_generation_in_milliseconds():
    board, cache = Board(), LeaderboardCache()
    snap = board.snapshot()
    for agg in AGGS:
        assert len(cache.job_aggregates.rolled(snap, SCHEMA, agg)) == TRAININGS
    timings = []
    for _ in range(3):
        board.improve(5)
        snap = board.snapshot()
        # The Jobs page derives what every answer shares: base, job tree, rollups.
        cache.page(snap, SCHEMA, limit=50, top=True)
        start = time.perf_counter()
        for agg in AGGS:
            cache.job_aggregates.rolled(snap, SCHEMA, agg)
        timings.append(time.perf_counter() - start)
    print(f"\nrolled after a delta (ms): {[round(t * 1000, 1) for t in timings]}")
    assert min(timings) <= 0.020, timings
