"""Pure-function tests for fleet_summary — per-child status counts and progress.

No git, no docker, no storage — these guard the fleet metrics contract that the
UI detail API serves for outer runs.
"""
import datetime

from version_stamp.core.experiment_status import (
    CREATED,
    FAILED,
    RUNNING,
    STUCK,
    SUCCEEDED,
)
from version_stamp.core.experiment_tree import fleet_summary
from version_stamp.ui.readers.experiment_detail import _DETAIL_STATUS_KEYS


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _ago(seconds):
    return _iso(_now() - datetime.timedelta(seconds=seconds))


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


def _succeeded(**kw):
    state = {
        "state": "finished",
        "started_at": _ago(600),
        "finished_at": _ago(10),
        "exit_code": 0,
        "heartbeat": _ago(10),
        "heartbeat_interval_sec": 30,
    }
    state.update(kw)
    return state


def _failed(**kw):
    state = {
        "state": "finished",
        "started_at": _ago(600),
        "finished_at": _ago(10),
        "exit_code": 1,
        "heartbeat": _ago(10),
        "heartbeat_interval_sec": 30,
    }
    state.update(kw)
    return state


# ---- fleet_summary basic ------------------------------------------------


def test_fleet_summary_basic():
    """3 children with different statuses, expected=5 -> correct counts + waiting=2."""
    children_of = {"parent": ["child1", "child2", "child3"]}
    states = {
        "child1": _running(),
        "child2": _succeeded(),
        "child3": _failed(),
    }

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        observed_at=None,
        expected=5,
    )

    assert result is not None
    assert result["expected"] == 5
    assert result["counts"][RUNNING] == 1
    assert result["counts"][SUCCEEDED] == 1
    assert result["counts"][FAILED] == 1
    assert result["counts"][STUCK] == 0
    assert result["counts"][CREATED] == 0
    assert result["counts"]["waiting"] == 2
    assert len(result["children"]) == 3
    # Each child entry has verstr and status
    by_v = {c["verstr"]: c for c in result["children"]}
    assert by_v["child1"]["status"] == RUNNING
    assert by_v["child2"]["status"] == SUCCEEDED
    assert by_v["child3"]["status"] == FAILED


# ---- fleet_summary no children ------------------------------------------


def test_fleet_summary_no_children():
    """Run with no children -> returns None."""
    children_of = {}
    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: None,
    )
    assert result is None


# ---- fleet_summary no expected ------------------------------------------


def test_fleet_summary_no_expected():
    """expected not set -> defaults to len(children), waiting=0."""
    children_of = {"parent": ["child1", "child2"]}
    states = {
        "child1": _running(),
        "child2": _succeeded(),
    }

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
    )

    assert result is not None
    assert result["expected"] == 2
    assert result["counts"]["waiting"] == 0
    assert result["counts"][RUNNING] == 1
    assert result["counts"][SUCCEEDED] == 1


# ---- fleet_summary with progress ----------------------------------------


def test_fleet_summary_with_progress():
    """Children with progress metrics in their rows."""
    children_of = {"parent": ["child1", "child2", "child3"]}
    states = {
        "child1": _running(),
        "child2": _running(),
        "child3": _succeeded(),
    }
    rows = {
        "child1": {"metrics": {"progress": 42, "progress_total": 100}, "params": {}},
        "child2": {"metrics": {}, "params": {"progress": 7, "progress_total": 20}},
        "child3": {"metrics": {"progress": 100, "progress_total": 100}, "params": {}},
    }

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        read_child_row=lambda v: rows.get(v),
    )

    by_v = {c["verstr"]: c for c in result["children"]}
    assert by_v["child1"]["progress"] == 42
    assert by_v["child1"]["progress_total"] == 100
    # Falls back to params when metrics don't have it
    assert by_v["child2"]["progress"] == 7
    assert by_v["child2"]["progress_total"] == 20
    assert by_v["child3"]["progress"] == 100


def test_fleet_summary_progress_missing():
    """Progress is None when row has no progress fields."""
    children_of = {"parent": ["child1"]}
    states = {"child1": _running()}
    rows = {"child1": {"metrics": {"loss": 0.5}, "params": {"lr": 0.01}}}

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        read_child_row=lambda v: rows.get(v),
    )

    assert result["children"][0]["progress"] is None
    assert result["children"][0]["progress_total"] is None


def test_fleet_summary_progress_non_numeric():
    """Non-numeric progress values are treated as None."""
    children_of = {"parent": ["child1"]}
    states = {"child1": _running()}
    rows = {"child1": {"metrics": {"progress": "halfway"}, "params": {}}}

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        read_child_row=lambda v: rows.get(v),
    )

    assert result["children"][0]["progress"] is None


# ---- fleet_summary cap children detail ----------------------------------


def test_fleet_summary_cap_children_detail():
    """More than 50 children -> only first 50 in detail, but counts cover all."""
    from version_stamp.core.experiment_tree import FLEET_MAX_CHILDREN_DETAIL

    n = FLEET_MAX_CHILDREN_DETAIL + 10
    child_names = [f"child{i}" for i in range(n)]
    children_of = {"parent": child_names}
    states = {name: _running() for name in child_names}

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
    )

    assert len(result["children"]) == FLEET_MAX_CHILDREN_DETAIL
    assert result["counts"][RUNNING] == n
    assert result["expected"] == n


# ---- fleet_summary negative expected ------------------------------------


def test_fleet_summary_negative_expected():
    """Negative expected is clamped to len(children)."""
    children_of = {"parent": ["child1"]}
    states = {"child1": _running()}

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        expected=-1,
    )

    assert result["expected"] == 1
    assert result["counts"]["waiting"] == 0


def test_fleet_summary_expected_less_than_children():
    """expected_pods=5 but 8 children visible -> expected=8."""
    child_names = [f"child{i}" for i in range(8)]
    children_of = {"parent": child_names}
    states = {name: _running() for name in child_names}

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        expected=5,
    )

    assert result["expected"] == 8
    assert result["counts"][RUNNING] == 8
    assert result["counts"]["waiting"] == 0


# ---- fleet_summary with observed_at ------------------------------------


def test_fleet_summary_with_observed_at():
    """observed_at callback is passed through to derive_status."""
    children_of = {"parent": ["child1"]}
    # Stale heartbeat but recent observed_at -> still running
    states = {"child1": _running(heartbeat_age=200)}
    recent = _now() - datetime.timedelta(seconds=5)

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        observed_at=lambda v: recent,
    )

    assert result["counts"][RUNNING] == 1


# ---- fleet_summary read_child_row returns None --------------------------


def test_fleet_summary_read_child_row_returns_none():
    """read_child_row returning None leaves progress as None."""
    children_of = {"parent": ["child1"]}
    states = {"child1": _running()}

    result = fleet_summary(
        "parent",
        children_of,
        read_state=lambda v: states.get(v),
        read_child_row=lambda v: None,
    )

    assert result["children"][0]["progress"] is None
    assert result["children"][0]["progress_total"] is None


# ---- status_detail includes fleet key -----------------------------------


def test_detail_status_keys_include_fleet():
    """_DETAIL_STATUS_KEYS must include 'fleet' so the detail response has it."""
    assert "fleet" in _DETAIL_STATUS_KEYS
