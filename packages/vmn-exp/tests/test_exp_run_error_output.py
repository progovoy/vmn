"""`vmn-exp run` records a failed child's ``error`` from its captured output.

The supervisor cannot catch the child's exception, but the child's traceback
is in the ``output.log`` it already keeps: the final ``run_state.yml`` gets
``error`` parsed from it (``source: output``). ``rerun`` supervises the same
way, so a failed rerun gets it too.
"""
import json
import signal

import pytest
from exp_helpers import _PY, _bootstrap, _exp, _storage, extract_dev_verstr
from rerun_helpers import original_run, rerun

from vmn_exp.core.status import load_run_state

from test_fix_exp_run_signals import _finish, _start_supervisor, _wait_for_live_run

_RAISE = "print('epoch 1', flush=True)\nraise ValueError('bad lr')\n"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _run(app_layout, capfd, script, extra_args=None):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="run", run_cmd=[_PY, "-c", script],
                extra_args=extra_args)
    return code, extract_dev_verstr(capfd.readouterr().out)


def _state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def test_a_traceback_in_the_output_is_the_runs_error(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr = _run(app_layout, capfd, _RAISE)

    assert code == 1
    error = _state(app_layout, verstr)["error"]
    assert error["source"] == "output"
    assert error["type"] == "ValueError"
    assert error["message"] == "bad lr"
    assert error["traceback"].startswith("Traceback (most recent call last):")
    assert "epoch 1" in error["output_tail"]


def test_a_failure_without_a_traceback_keeps_the_output_tail(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr = _run(app_layout, capfd, "import sys\nprint('disk full')\nsys.exit(3)\n")

    assert code == 3
    error = _state(app_layout, verstr)["error"]
    assert error == {"source": "output", "output_tail": "disk full"}


def test_a_successful_run_records_no_error(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr = _run(app_layout, capfd, "print('fine')\n")
    assert code == 0
    assert "error" not in _state(app_layout, verstr)


def test_no_capture_output_records_no_error(app_layout, capfd):
    _bootstrap(app_layout)
    code, verstr = _run(app_layout, capfd, _RAISE, extra_args=["--no-capture-output"])
    assert code == 1
    assert "error" not in _state(app_layout, verstr)


def test_a_signalled_child_keeps_its_signal_and_gets_the_output_error(app_layout, tmp_path):
    _bootstrap(app_layout)
    marker = str(tmp_path / "up")
    child = (
        "import time\n"
        "print('loading data', flush=True)\n"
        f"open({marker!r}, 'w').close()\n"
        "time.sleep(60)\n"
    )
    proc = _start_supervisor(app_layout, child)
    verstr, _ = _wait_for_live_run(app_layout, marker)

    proc.send_signal(signal.SIGTERM)
    _finish(proc)

    state = _state(app_layout, verstr)
    assert state["signal"] == "SIGTERM"
    assert "loading data" in state["error"]["output_tail"]


def test_show_prints_the_error_block_and_json_carries_it(app_layout, capfd):
    _bootstrap(app_layout)
    _, verstr = _run(app_layout, capfd, _RAISE)

    assert _exp(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    assert "  Error:     ValueError: bad lr" in out
    assert "    Traceback (most recent call last):" in out

    assert _exp(app_layout.app_name, action="show", version=verstr,
                extra_args=["--json"]) == 0
    payload = json.loads(capfd.readouterr().out)
    assert payload["error"]["type"] == "ValueError"


def test_a_failed_rerun_records_the_output_error(app_layout, capfd):
    orig = original_run(app_layout)
    rc, new = rerun(app_layout, orig, run_cmd=[_PY, "-c", _RAISE])

    assert rc == 1 and new
    assert _state(app_layout, new)["error"]["type"] == "ValueError"
