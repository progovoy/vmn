"""A restart serves the persisted index at once (plan 23 S9).

At 100k runs a restarted ``vmn-exp ui`` spent ~40s listing the store before
its first snapshot, though every row was already persisted. Now the first
:meth:`ExperimentIndex.snapshot` answers the persisted rows as soon as they
are read and the storage listing revalidates them in the background
(stale-while-revalidate); :meth:`refresh_if_stale` still refreshes first.
"""
import threading

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.status import derive_status
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
RUNNING = "state: running\nheartbeat: '{hb}'\nheartbeat_interval_sec: 30\n"
FINISHED = "state: finished\nexit_code: 0\n"


class GatedStorage(LocalSnapshotStorage):
    """Its listings wait for :attr:`gate`; :attr:`listed` counts those done."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()
        self.listed = 0

    def list_files(self, app_name, keys=None, identity=False):
        self.gate.wait(30)
        files = super().list_files(app_name, keys=keys, identity=identity)
        self.listed += 1
        return files


def _make(st, i, run_state=FINISHED, loss=None):
    verstr = f"0.0.1-dev.abc.r{i}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}
    st.save(APP, verstr, meta, {})
    _log_loss(st, verstr, float(i) if loss is None else loss)
    st.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


def _log_loss(st, verstr, loss):
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics",
                                           "values": {"loss": loss}})


def _persisted(tmp_path, runs=3, **kwargs):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    verstrs = [_make(st, i, **kwargs) for i in range(runs)]
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    return st, verstrs, db


def _losses(snap):
    return {row["verstr"]: row["metrics"].get("loss") for row in snap.rows}


def test_a_restart_serves_the_persisted_rows_before_listing_storage(tmp_path):
    _, verstrs, db = _persisted(tmp_path)
    gated = GatedStorage(str(tmp_path), area="runs")
    index = ExperimentIndex(gated, APP, cache_path=db)

    snap = index.snapshot()

    assert gated.listed == 0
    assert [row["verstr"] for row in snap.rows] == verstrs
    assert _losses(snap) == {v: float(i) for i, v in enumerate(verstrs)}
    gated.gate.set()
    index.wait_revalidated()
    assert gated.listed >= 1


def test_the_background_refresh_picks_up_what_changed_while_down(tmp_path):
    st, verstrs, db = _persisted(tmp_path, run_state=RUNNING.format(hb="2026-01-01T00:00:00Z"))
    new = _make(st, 7)
    _log_loss(st, verstrs[0], 0.5)
    st.save_file(APP, verstrs[1], "run_state.yml", FINISHED)
    gated = GatedStorage(str(tmp_path), area="runs")
    index = ExperimentIndex(gated, APP, cache_path=db)

    stale = index.snapshot()
    gated.gate.set()
    index.wait_revalidated()
    fresh = index.snapshot()

    assert new not in _losses(stale)
    assert fresh.generation > stale.generation
    assert _losses(fresh)[new] == 7.0
    assert _losses(fresh)[verstrs[0]] == 0.5
    assert derive_status(fresh.run_states[verstrs[1]]) == "succeeded"
    # A run the server last saw running, unheard of since: stuck by now.
    assert derive_status(fresh.run_states[verstrs[2]]) == "stuck"


def test_refresh_if_stale_still_refreshes_before_answering(tmp_path):
    st, _, db = _persisted(tmp_path)
    new = _make(st, 8)

    snap = ExperimentIndex(st, APP, cache_path=db).refresh_if_stale(0)

    assert new in _losses(snap)


def test_a_warm_snapshot_counts_as_stale_for_refresh_if_stale(tmp_path):
    st, _, db = _persisted(tmp_path)
    new = _make(st, 9)
    gated = GatedStorage(str(tmp_path), area="runs")
    index = ExperimentIndex(gated, APP, cache_path=db)
    index.snapshot()
    gated.gate.set()
    index.wait_revalidated()  # the revalidation, then:

    assert new in _losses(index.refresh_if_stale(3600))


def test_a_cold_index_still_lists_before_its_first_snapshot(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    verstr = _make(st, 1)

    snap = ExperimentIndex(st, APP, cache_path=str(tmp_path / "idx.sqlite")).snapshot()

    assert [row["verstr"] for row in snap.rows] == [verstr]
