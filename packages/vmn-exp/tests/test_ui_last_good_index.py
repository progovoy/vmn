"""A failed or stuck run's ``last_good`` (plan 20 K4) comes from a per-snapshot
index of the succeeded runs by command, moved from one generation to the next
by its delta: a run-detail request looks it up instead of walking the app's
earlier rows (709k on a big app) and deriving each one's status."""
import itertools
import time

import pytest

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.ui.readers.baselines import last_good

_APPS = itertools.count()


class _State(dict):
    """A run state counting every field read off it."""

    reads = 0

    def get(self, *args):
        _State.reads += 1
        return super().get(*args)


def _state(command="train", exit_code=1):
    return _State(command=command, exit_code=exit_code, state="ended")


def _row(n, **extra):
    return {"verstr": f"v{n}", "idx": n + 1, "name": f"n{n}", "parent": None, **extra}


def _snapshot(rows, states, app=None, generation=1):
    return IndexSnapshot.build(app or f"app{next(_APPS)}", generation, rows, states)


def _app(n, command="train", exit_code=1):
    rows = [_row(i) for i in range(n)]
    return rows, {r["verstr"]: _state(command, exit_code) for r in rows}


def _verstr(found):
    return found and found["verstr"]


def test_it_is_the_latest_earlier_unarchived_success_of_the_command():
    rows = [_row(0), _row(1), _row(2, archived=True), _row(3), _row(4), _row(5)]
    states = {"v0": _state(exit_code=0), "v1": _state(exit_code=0), "v2": _state(exit_code=0),
              "v3": _state("other", 0), "v4": _state(), "v5": _state(exit_code=0)}
    snap = _snapshot(rows, states)
    assert last_good(snap, "v4") == {"verstr": "v1", "idx": 2, "name": "n1"}
    assert last_good(snap, "v0") is None
    assert last_good(snap, "missing") is None


def test_a_command_that_never_succeeded_has_none():
    rows, states = _app(50)
    assert last_good(_snapshot(rows, states), "v49") is None


def test_a_repeat_request_reads_no_run_states():
    rows, states = _app(20_000)
    snap = _snapshot(rows, states)
    last_good(snap, "v19999")
    _State.reads = 0
    assert last_good(snap, "v19998") is None
    assert _State.reads <= 5


def test_a_new_generation_reads_only_the_runs_that_changed():
    rows, states = _app(20_000)
    app = f"app{next(_APPS)}"
    last_good(_snapshot(rows, states, app), "v19999")
    states = dict(states, v100=_state(exit_code=0))
    rows = rows + [_row(20_000), _row(20_001)]
    states.update(v20000=_state(exit_code=0), v20001=_state())
    _State.reads = 0
    nxt = _snapshot(rows, states, app, generation=2)
    assert _verstr(last_good(nxt, "v19999")) == "v100"
    assert _verstr(last_good(nxt, "v20001")) == "v20000"
    assert _State.reads <= 20


def test_a_success_that_changes_again_leaves_the_index():
    rows, states = _app(30)
    states["v3"] = _state(exit_code=0)
    app = f"app{next(_APPS)}"
    assert _verstr(last_good(_snapshot(rows, states, app), "v29")) == "v3"
    states = dict(states, v3=_state(exit_code=1))
    rows = rows[:10] + [_row(10, archived=True)] + rows[11:]
    states["v10"] = _state(exit_code=0)
    assert last_good(_snapshot(rows, states, app, 2), "v29") is None


def test_fewer_rows_rebuild_it():
    rows, states = _app(30)
    states["v20"] = _state(exit_code=0)
    app = f"app{next(_APPS)}"
    assert _verstr(last_good(_snapshot(rows, states, app), "v25")) == "v20"
    rows = rows[:21] + rows[22:]
    states.pop("v21")
    states["v20"] = _state(exit_code=1)
    snap = _snapshot([dict(r, idx=i + 1) for i, r in enumerate(rows)], states, app, 2)
    assert last_good(snap, "v25") is None


@pytest.mark.serial
def test_a_unique_command_on_a_big_app_is_a_lookup():
    rows = [_row(i) for i in range(300_000)]
    states = {r["verstr"]: _state(f"cmd {i}") for i, r in enumerate(rows)}
    snap = _snapshot(rows, states)
    last_good(snap, "v299999")
    started = time.perf_counter()
    for n in range(299_990, 300_000):
        assert last_good(snap, f"v{n}") is None
    assert (time.perf_counter() - started) / 10 < 0.002
