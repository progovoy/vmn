"""Scale guard (plan 34 §4): a restart onto a file of older records (19,
upgraded in place) publishes rows in a fraction of a second whatever the
store's size: the open reads no record, and the newest kept rows serve
before the kept read and the re-derive (O(runs): ~8 minutes at fgm's 734k
runs). Timed, so serial."""
import time

import pytest
from test_index_upgrade_records_19 import _as_records_19
from uiload import seeder
from vmn_exp.core.index import FIRST_ROWS_MAX, ExperimentIndex

from vmn_exp.snapshot import LocalSnapshotStorage

APP = "benchapp"
RUNS = 20_000
FIRST_PUBLISH_SEC = 0.5


@pytest.fixture(scope="module")
def outdated(tmp_path_factory):
    root = tmp_path_factory.mktemp("upgrade_first_publish_bench")
    seeder.seed(str(root), app=APP, runs=RUNS, sweeps=4, inner_per_sweep=200,
                max_metric_keys=8, max_steps=50, max_params=8)
    db = str(root / "idx.sqlite")
    ExperimentIndex(_storage(root), APP, cache_path=db).refresh().close()
    _as_records_19(db)
    return root, db


def _storage(root):
    storage = LocalSnapshotStorage(str(root / ".vmn" / "store"), area="runs")
    storage.is_remote = lambda: True
    return storage


@pytest.mark.serial
def test_an_upgraded_restart_publishes_rows_at_once(outdated):
    root, db = outdated
    started = time.perf_counter()
    index = ExperimentIndex(_storage(root), APP, cache_path=db)
    opened = time.perf_counter() - started
    first = index.snapshot_now(wait_sec=FIRST_PUBLISH_SEC)
    while not first.rows and time.perf_counter() - started < 30:
        first = index.snapshot_now(wait_sec=0.05)
    served = time.perf_counter() - started
    full = index.snapshot()
    index.wait_revalidated()
    done = time.perf_counter() - started
    index.close()

    print(f"\n{RUNS} runs at records 19: opened in {opened:.3f}s, {len(first.rows)} rows"
          f" after {served:.3f}s, every row after {done:.2f}s")
    assert 0 < len(first.rows) <= FIRST_ROWS_MAX
    assert first.loading[1] == len(full.rows)
    assert served <= FIRST_PUBLISH_SEC
