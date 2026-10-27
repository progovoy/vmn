"""A refresh is stuck only when it stops moving, not when it runs long: a cold
load of a 500k-run store runs over an hour while it publishes runs, and the
dashboard called it failing ("The background refresh has not completed")
after 10 minutes. The index reports ``stalled_sec`` while a refresh runs — how
long its reported phase and progress have not changed — and the ui counts a refresh past
``STUCK_REFRESH_SEC`` as failing only when it also stalled that long."""
import threading

import pytest

from test_index_freshness import APP, N, _storage, s3, wall  # noqa: F401  (fixtures)
import vmn_exp.core.index as index_module
from vmn_exp.core.index import ExperimentIndex

pytest.importorskip("fastapi")
from vmn_exp.ui.freshness import STUCK_REFRESH_SEC, freshness  # noqa: E402

HEALTHY = {"alive": True, "failing": False, "failures": 0, "since_refresh_sec": None,
           "refreshing_sec": 3600.0, "last_error": None}
LOADING = {"as_of": None, "refreshing": True, "phase": "loading_new", "progress": 0.25}


def test_a_long_refresh_that_keeps_moving_is_not_failing():
    fresh = freshness(HEALTHY, dict(LOADING, stalled_sec=4.0))

    assert not fresh["refresh_failing"]
    assert fresh["refresh_running_sec"] == 3600


def test_a_long_refresh_that_stopped_moving_is_failing():
    assert freshness(HEALTHY, dict(LOADING, stalled_sec=STUCK_REFRESH_SEC))["refresh_failing"]


def test_a_short_stall_of_a_short_refresh_is_not_failing():
    health = dict(HEALTHY, refreshing_sec=STUCK_REFRESH_SEC - 1)

    assert not freshness(health, dict(LOADING, stalled_sec=STUCK_REFRESH_SEC))["refresh_failing"]


def test_the_index_reports_how_long_its_refresh_has_not_moved(s3, tmp_path, monkeypatch, wall):
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", 4)
    storage, seen, lock = _storage(), [], threading.Lock()
    index = ExperimentIndex(storage, APP, str(tmp_path / "i.sqlite"))
    load, count = storage.load_file, [0]
    start = wall[0]

    def load_file(app_name, verstr, filename):
        if filename == "metadata.yml":
            with lock:
                count[0] += 1
                if count[0] in (5, 6, 9):  # 2nd chunk starts, still in it, 3rd starts
                    wall[0] = start + {5: 0, 6: 700, 9: 800}[count[0]]
                    seen.append(index.freshness())
        return load(app_name, verstr, filename)

    storage.load_file = load_file
    index.refresh()

    assert [s["progress"] for s in seen] == [round(4 / N, 3)] * 2 + [round(8 / N, 3)]
    assert [s["stalled_sec"] for s in seen] == [0, 700, 0]
    assert index.freshness().get("stalled_sec") is None  # between refreshes
