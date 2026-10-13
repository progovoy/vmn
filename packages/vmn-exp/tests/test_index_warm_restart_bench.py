"""Scale guard (plan 23 S9): a restarted index serves its first snapshot from
the persisted rows in about a second at 20k runs, without waiting for the
storage listing (~40s at 100k before). The first-ever build is timed and
reported, not asserted (it reads every record). Timed, so serial."""
import time

import pytest
from uiload import seeder

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "benchapp"
RUNS = 20_000
RESTART_SEC = 1.0


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("warm_restart_bench")
    seeder.seed(str(root), app=APP, runs=RUNS, sweeps=4, inner_per_sweep=200,
                max_metric_keys=8, max_steps=50, max_params=8)
    return root


def _storage(root):
    return LocalSnapshotStorage(str(root / ".vmn" / "store"), area="runs")


@pytest.mark.serial
def test_a_restart_serves_the_persisted_snapshot_within_a_second(store):
    db = str(store / "idx.sqlite")
    started = time.perf_counter()
    first = ExperimentIndex(_storage(store), APP, cache_path=db).snapshot()
    built = time.perf_counter() - started

    restarted = ExperimentIndex(_storage(store), APP, cache_path=db)
    started = time.perf_counter()
    snap = restarted.snapshot()
    served = time.perf_counter() - started
    restarted.wait_revalidated()
    revalidated = time.perf_counter() - started

    print(f"\n{RUNS} runs: first build {built:.2f}s, restart {served:.2f}s "
          f"(revalidated after {revalidated:.2f}s)")
    assert len(first.rows) == len(snap.rows) == RUNS
    assert served <= RESTART_SEC
    assert restarted.snapshot().generation == snap.generation  # nothing moved
