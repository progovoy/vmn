"""A failed run's ``error`` reaches the run-detail API, ``show`` and alerts."""
import pytest
import yaml

from vmn_exp.cli.views import error_lines, show_payload
from vmn_exp.core.alerts.transitions import transition_alert
from vmn_exp.core.status import FAILED, RUN_STATE_FILE

_ERROR = {
    "type": "ValueError",
    "message": "bad lr",
    "traceback": "Traceback (most recent call last):\n  File \"t.py\"\nValueError: bad lr",
    "source": "output",
    "output_tail": "epoch 1\nValueError: bad lr",
}
_FAILED = {"state": "finished", "exit_code": 1, "finished_at": "2026-10-01T10:00:00Z",
           "error": _ERROR}


def test_error_lines_print_the_summary_then_the_indented_traceback():
    lines = error_lines(_ERROR)
    assert lines[0] == "ValueError: bad lr"
    assert lines[1:] == ["  Traceback (most recent call last):", '    File "t.py"',
                         "  ValueError: bad lr"]


def test_error_lines_fall_back_to_the_output_tail():
    error = {"source": "output", "output_tail": "oom\nKilled"}
    assert error_lines(error) == ["Killed", "  oom", "  Killed"]


def test_error_lines_without_an_error():
    assert error_lines(None) == []


def test_show_payload_carries_the_error():
    payload = show_payload(0, {"verstr": "0.0.1"}, {}, [], _FAILED, {})
    assert payload["error"] == _ERROR
    assert show_payload(0, {"verstr": "0.0.1"}, {}, [], None, {})["error"] is None


def test_failure_alert_text_carries_the_error_summary():
    alert = transition_alert("app", "0.0.1", _FAILED, FAILED)
    assert "exit code 1" in alert["text"]
    assert "ValueError: bad lr" in alert["text"]


def test_failure_alert_without_an_error_is_unchanged():
    state = dict(_FAILED, error=None, signal="SIGKILL", exit_code=137)
    assert transition_alert("app", "0.0.1", state, FAILED)["text"] == "exit code 137 (SIGKILL)"


pytest.importorskip("fastapi")
from test_fix_ui_api_detail import APP, BASE, _record, ws  # noqa: E402,F401


def _save_state(storage, verstr, state):
    storage.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(state))


def test_detail_status_carries_the_full_error(ws):  # noqa: F811
    client, storage = ws
    _record(storage, "1.0.0-dev.e")
    _save_state(storage, "1.0.0-dev.e", {"state": "running", "pid": 1})
    first = client.get(f"{BASE}/1.0.0-dev.e")
    assert first.json()["status"]["error"] is None

    _save_state(storage, "1.0.0-dev.e", _FAILED)
    again = client.get(f"{BASE}/1.0.0-dev.e", headers={"If-None-Match": first.headers["etag"]})

    assert again.status_code == 200
    status = again.json()["status"]
    assert status["error"] == _ERROR
    assert status["error_summary"] == "ValueError: bad lr"


def test_list_rows_never_carry_the_full_error(ws):  # noqa: F811
    client, storage = ws
    _record(storage, "1.0.0-dev.e")
    _save_state(storage, "1.0.0-dev.e", _FAILED)
    rows = client.get(BASE).json()
    rows = rows["experiments"] if isinstance(rows, dict) else rows
    (row,) = [r for r in rows if r["verstr"] == "1.0.0-dev.e"]
    assert row["error_summary"] == "ValueError: bad lr"
    assert "error" not in row
