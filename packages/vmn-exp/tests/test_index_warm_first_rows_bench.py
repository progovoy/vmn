"""Scale guard: a restarted index on a remote store serves its newest
persisted rows in a fraction of a second whatever the store's size — before
reading every persisted row back, which is O(runs) (seconds at 20k runs,
minutes at ~700k on a server). Timed, so serial."""
import time

import pytest
from uiload import seeder
from vmn_exp.core.index import FIRST_ROWS, FIRST_ROWS_MAX, ExperimentIndex

from vmn_exp.snapshot import LocalSnapshotStorage

APP = "benchapp"
RUNS = 20_000
FIRST_ROWS_SEC = 0.3


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("warm_first_rows_bench")
    seeder.seed(str(root), app=APP, runs=RUNS, sweeps=4, inner_per_sweep=200,
                max_metric_keys=8, max_steps=50, max_params=8)
    db = str(root / "idx.sqlite")
    ExperimentIndex(_storage(root), APP, cache_path=db).refresh()
    return root, db


def _storage(root):
    storage = LocalSnapshotStorage(str(root / ".vmn" / "store"), area="runs")
    storage.is_remote = lambda: True
    return storage


@pytest.mark.serial
def test_a_restart_serves_its_newest_rows_before_reading_every_row_back(store):
    root, db = store
    index = ExperimentIndex(_storage(root), APP, cache_path=db)
    started = time.perf_counter()
    first = index.snapshot_now(wait_sec=FIRST_ROWS_SEC)
    served = time.perf_counter() - started
    full = index.snapshot()
    persisted = time.perf_counter() - started
    index.wait_revalidated()

    print(f"\n{RUNS} runs: newest {len(first.rows)} rows after {served:.3f}s, "
          f"every persisted row after {persisted:.2f}s")
    # The newest runs, plus the outer runs and parents around them.
    assert first.loading == (len(first.rows), len(full.rows))
    assert len(first.rows) <= FIRST_ROWS_MAX
    shown = [r["verstr"] for r in first.rows]
    assert {r["verstr"] for r in full.rows[-FIRST_ROWS:]} <= set(shown)
    order = {r["verstr"]: i for i, r in enumerate(full.rows)}
    assert shown == sorted(shown, key=order.__getitem__)  # the full snapshot's order
    assert served <= FIRST_ROWS_SEC
