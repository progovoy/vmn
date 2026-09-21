"""Pure-function tests for experiment run status + nesting derivation.

No git, no docker, no storage — these guard the shared contract that the CLI,
the ui readers and the web frontend all agree on.
"""
import datetime

import pytest

from version_stamp.core import experiment_status as st
from version_stamp.core import experiment_tree as tr


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


NOW = datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _ago(seconds):
    return _iso(NOW - datetime.timedelta(seconds=seconds))


def _running(heartbeat_age=5, interval=30, **kw):
    state = {
        "state": "running",
        "command": ["python", "train.py"],
        "pid": 4242,
        "host": "box",
        "started_at": _ago(600),
        "heartbeat": _ago(heartbeat_age),
        "heartbeat_interval_sec": interval,
        "exit_code": None,
        "finished_at": None,
    }
    state.update(kw)
    return state


# ---- derive_status ---------------------------------------------------------


def test_no_run_state_is_created():
    assert st.derive_status(None, now=NOW) == st.CREATED
    assert st.derive_status({}, now=NOW) == st.CREATED


def test_fresh_heartbeat_is_running():
    assert st.derive_status(_running(heartbeat_age=5), now=NOW) == st.RUNNING


def test_heartbeat_within_grace_is_still_running():
    # stale_after = max(3 * 30, 60) = 90
    assert st.derive_status(_running(heartbeat_age=89), now=NOW) == st.RUNNING


def test_stale_heartbeat_is_stuck():
    assert st.derive_status(_running(heartbeat_age=91), now=NOW) == st.STUCK


def test_short_interval_still_gets_minimum_grace():
    # 3 * 1s would flag a healthy run as stuck; MIN_STALE_SEC floors it.
    assert st.stale_after_sec(_running(interval=1)) == st.MIN_STALE_SEC
    assert st.derive_status(_running(heartbeat_age=30, interval=1), now=NOW) == st.RUNNING


def test_long_interval_scales_the_grace_window():
    assert st.stale_after_sec(_running(interval=300)) == 900
    assert st.derive_status(_running(heartbeat_age=800, interval=300), now=NOW) == (
        st.RUNNING
    )


def test_running_without_heartbeat_falls_back_to_started_at():
    state = _running(heartbeat=None, started_at=_ago(5))
    assert st.derive_status(state, now=NOW) == st.RUNNING
    state = _running(heartbeat=None, started_at=_ago(5000))
    assert st.derive_status(state, now=NOW) == st.STUCK


def test_running_with_unparseable_heartbeat_is_stuck():
    assert st.derive_status(_running(heartbeat="not-a-date"), now=NOW) == st.STUCK


def test_finished_zero_exit_is_succeeded():
    state = _running(state="finished", exit_code=0, finished_at=_ago(10))
    assert st.derive_status(state, now=NOW) == st.SUCCEEDED


def test_finished_nonzero_exit_is_failed():
    state = _running(state="finished", exit_code=137, finished_at=_ago(10))
    assert st.derive_status(state, now=NOW) == st.FAILED


def test_exit_code_wins_over_a_stale_heartbeat():
    """A run that finished long ago must not decay into 'stuck'."""
    state = _running(state="finished", exit_code=0, heartbeat_age=99999)
    assert st.derive_status(state, now=NOW) == st.SUCCEEDED


# ---- status_fields --------------------------------------------------------


def test_status_fields_for_a_running_job():
    fields = st.status_fields(_running(heartbeat_age=5), now=NOW)
    assert fields["status"] == st.RUNNING
    assert fields["pid"] == 4242
    assert fields["host"] == "box"
    assert fields["command"] == ["python", "train.py"]
    assert fields["exit_code"] is None
    assert fields["finished_at"] is None
    assert fields["stale_sec"] == pytest.approx(5, abs=1)
    # elapsed wall time so far, not a recorded duration
    assert fields["duration_sec"] == pytest.approx(600, abs=1)
    # the dashboard sizes its poll interval from this, so it must be serialized
    assert fields["heartbeat_interval_sec"] == 30


def test_status_fields_defaults_the_heartbeat_interval():
    fields = st.status_fields(_running(interval=None), now=NOW)
    assert fields["heartbeat_interval_sec"] == st.DEFAULT_HEARTBEAT_INTERVAL_SEC


def test_status_fields_prefers_the_recorded_duration_when_finished():
    state = _running(state="finished", exit_code=0, duration_sec=12.5)
    fields = st.status_fields(state, now=NOW)
    assert fields["status"] == st.SUCCEEDED
    assert fields["duration_sec"] == 12.5


def test_status_fields_without_run_state():
    fields = st.status_fields(None, now=NOW)
    assert fields["status"] == st.CREATED
    assert fields["duration_sec"] is None
    assert fields["stale_sec"] is None
    assert fields["command"] is None


# ---- rollup_status --------------------------------------------------------


@pytest.mark.parametrize(
    "children,expected",
    [
        ([], None),
        ([st.SUCCEEDED, st.SUCCEEDED], st.SUCCEEDED),
        ([st.SUCCEEDED, st.RUNNING], st.RUNNING),
        ([st.RUNNING, st.STUCK], st.STUCK),
        ([st.FAILED, st.RUNNING, st.STUCK], st.FAILED),
        ([st.CREATED, st.SUCCEEDED], st.CREATED),
        ([st.CREATED, st.RUNNING], st.RUNNING),
    ],
)
def test_rollup_precedence(children, expected):
    assert tr.rollup_status(children) == expected


# ---- annotate_tree --------------------------------------------------------


def _row(verstr, parent=None, status=st.SUCCEEDED):
    return {"verstr": verstr, "parent": parent, "status": status}


def test_flat_rows_are_all_single():
    rows = tr.annotate_tree([_row("a"), _row("b")])
    for r in rows:
        assert r["kind"] == tr.SINGLE
        assert r["children"] == []
        assert r["depth"] == 0


def test_parent_becomes_outer_and_child_inner():
    rows = tr.annotate_tree([_row("sweep"), _row("t1", parent="sweep")])
    by_v = {r["verstr"]: r for r in rows}
    assert by_v["sweep"]["kind"] == tr.OUTER
    assert by_v["sweep"]["children"] == ["t1"]
    assert by_v["sweep"]["depth"] == 0
    assert by_v["t1"]["kind"] == tr.INNER
    assert by_v["t1"]["depth"] == 1
    assert by_v["t1"]["children"] == []


def test_outer_rolls_up_child_status():
    rows = tr.annotate_tree(
        [
            _row("sweep", status=st.SUCCEEDED),
            _row("t1", parent="sweep", status=st.SUCCEEDED),
            _row("t2", parent="sweep", status=st.FAILED),
        ]
    )
    sweep = next(r for r in rows if r["verstr"] == "sweep")
    assert sweep["status"] == st.SUCCEEDED, "own status must stay untouched"
    assert sweep["tree_status"] == st.FAILED


def test_own_status_participates_in_the_rollup():
    rows = tr.annotate_tree(
        [
            _row("sweep", status=st.STUCK),
            _row("t1", parent="sweep", status=st.SUCCEEDED),
        ]
    )
    sweep = next(r for r in rows if r["verstr"] == "sweep")
    assert sweep["tree_status"] == st.STUCK


def test_leaf_tree_status_is_its_own_status():
    rows = tr.annotate_tree([_row("a", status=st.RUNNING)])
    assert rows[0]["tree_status"] == st.RUNNING


def test_three_level_nesting_reports_depth():
    rows = tr.annotate_tree(
        [_row("a"), _row("b", parent="a"), _row("c", parent="b")]
    )
    by_v = {r["verstr"]: r for r in rows}
    assert [by_v[k]["depth"] for k in ("a", "b", "c")] == [0, 1, 2]
    assert by_v["b"]["kind"] == tr.OUTER  # both a parent and a child


def test_rollup_is_recursive_through_grandchildren():
    rows = tr.annotate_tree(
        [
            _row("a"),
            _row("b", parent="a"),
            _row("c", parent="b", status=st.FAILED),
        ]
    )
    by_v = {r["verstr"]: r for r in rows}
    assert by_v["a"]["tree_status"] == st.FAILED


def test_missing_parent_is_still_inner_at_depth_one():
    rows = tr.annotate_tree([_row("orphan", parent="gone")])
    assert rows[0]["kind"] == tr.INNER
    assert rows[0]["depth"] == 1


def test_parent_cycle_does_not_hang():
    rows = tr.annotate_tree([_row("a", parent="b"), _row("b", parent="a")])
    assert {r["verstr"] for r in rows} == {"a", "b"}
    for r in rows:
        assert r["depth"] >= 0


def test_children_are_ordered_by_input_order():
    rows = tr.annotate_tree(
        [_row("s"), _row("z", parent="s"), _row("a", parent="s")]
    )
    assert next(r for r in rows if r["verstr"] == "s")["children"] == ["z", "a"]


def test_annotate_tree_does_not_mutate_input():
    original = [_row("s"), _row("t", parent="s")]
    tr.annotate_tree(original)
    assert "children" not in original[0]
