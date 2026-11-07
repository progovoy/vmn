"""Plan 32 F13: a run that is not running and has no recorded end has no
duration (``duration_sec: null``), only a lower bound: ``duration_at_least_sec``
(its last proof of life minus its start). A dead run's duration no longer
keeps growing, and a ``duration_sec`` sort puts it after the known ones. Pure."""
import datetime

import pytest

from vmn_exp.core import status as st
from vmn_exp.core.field_sort import field_sort, sort_by_field
from vmn_exp.core.query import ROW_FIELDS

NOW = datetime.datetime(2026, 11, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _ago(seconds):
    return NOW - datetime.timedelta(seconds=seconds)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _state(heartbeat_age, started_age=10800, **kw):
    state = {
        "state": "running", "started_at": _iso(_ago(started_age)),
        "heartbeat": _iso(_ago(heartbeat_age)), "heartbeat_interval_sec": 30,
        "exit_code": None, "finished_at": None, "duration_sec": None,
    }
    state.update(kw)
    return state


def test_a_stuck_run_has_no_duration_only_a_lower_bound():
    fields = st.status_fields(_state(heartbeat_age=3600), now=NOW)
    assert fields["status"] == st.STUCK
    assert fields["duration_sec"] is None
    assert fields["duration_at_least_sec"] == pytest.approx(7200)


def test_the_lower_bound_uses_the_store_write_time_too():
    fields = st.status_fields(_state(heartbeat_age=9000), now=NOW, observed_at=_ago(3600))
    assert fields["status"] == st.STUCK
    assert fields["duration_at_least_sec"] == pytest.approx(7200)


def test_a_failed_run_without_a_recorded_end_has_a_lower_bound():
    fields = st.status_fields(_state(heartbeat_age=3600, exit_code=1), now=NOW)
    assert fields["status"] == st.FAILED
    assert fields["duration_sec"] is None
    assert fields["duration_at_least_sec"] == pytest.approx(7200)


def test_a_running_run_keeps_its_elapsed_time_and_no_lower_bound():
    fields = st.status_fields(_state(heartbeat_age=5), now=NOW)
    assert fields["status"] == st.RUNNING
    assert fields["duration_sec"] == pytest.approx(10800)
    assert fields["duration_at_least_sec"] is None


def test_a_finished_run_keeps_its_final_duration_and_no_lower_bound():
    recorded = st.status_fields(
        _state(heartbeat_age=3600, exit_code=0, duration_sec=12.5), now=NOW)
    assert (recorded["duration_sec"], recorded["duration_at_least_sec"]) == (12.5, None)
    ended = st.status_fields(
        _state(heartbeat_age=3600, exit_code=0, finished_at=_iso(_ago(3600))), now=NOW)
    assert ended["duration_sec"] == pytest.approx(7200)
    assert ended["duration_at_least_sec"] is None


def test_a_run_never_started_has_neither():
    fields = st.status_fields(None, now=NOW)
    assert fields["duration_sec"] is None
    assert fields["duration_at_least_sec"] is None


def test_the_lower_bound_is_a_query_field():
    assert "duration_at_least_sec" in ROW_FIELDS


def test_a_duration_sort_puts_the_lower_bounds_after_the_known_durations():
    rows = [
        {"verstr": "stuck", **st.status_fields(_state(heartbeat_age=600, started_age=99999), now=NOW)},
        {"verstr": "done", "duration_sec": 50},
        {"verstr": "long", "duration_sec": 500},
    ]
    for descending in (False, True):
        ordered = [r["verstr"] for r in sort_by_field(rows, field_sort("duration_sec"), descending)]
        assert ordered[-1] == "stuck"


@pytest.mark.parametrize("fields, text", [
    ({"status": st.SUCCEEDED, "duration_sec": 12.5, "duration_at_least_sec": None}, "12.5s"),
    ({"status": st.RUNNING, "duration_sec": 600, "duration_at_least_sec": None}, "600s (running)"),
    ({"status": st.STUCK, "duration_sec": None, "duration_at_least_sec": 11000}, "≥ 3h (stuck)"),
    ({"status": st.FAILED, "duration_sec": None, "duration_at_least_sec": 59}, "≥ 59s (failed)"),
    ({"status": st.CREATED, "duration_sec": None, "duration_at_least_sec": None}, None),
])
def test_cli_duration_text_marks_the_lower_bound(fields, text):
    from vmn_exp.cli.duration_text import duration_text

    assert duration_text(fields) == text
