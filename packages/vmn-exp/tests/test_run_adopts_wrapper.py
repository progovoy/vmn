"""`vmn-exp run -- python train.py` with ``start_run()`` in train.py is one
run (plan 38 A5): the script records into the supervisor's run, in a stream
of its own, and the supervisor records how the process ended. Real git."""
from datetime import datetime, timezone
import os

import pytest
from exp_helpers import _PY, _SRC_PATH, _bootstrap, _exec_script, _exp, _storage

from vmn_exp.core.metric_compact import record_compacted
from vmn_exp.core.rerun import RUNNER_CLI
from vmn_exp.core.status import derive_status, load_run_state
from vmn_exp.core.streams import GUEST_WRITER_SUFFIX, display_writer


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR", "VMN_EXP_ADOPT", "VMN_EXP_ADOPT_RUN_ID",
                "VMN_EXP_ADOPT_PID"):
        monkeypatch.delenv(key, raising=False)
    # The child imports this tree's SDK, not an installed one.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        p for p in (_SRC_PATH, os.environ.get("PYTHONPATH")) if p))


TRAIN = (
    "import sys\n"
    "from vmn_exp.sdk import start_run\n"
    "with start_run(params={'lr': 0.1}) as run:\n"
    "    run.log_metric('loss', 0.25)\n"
    "print('SDK_RUN', run.id)\n"
)


def _run(app_layout, body, *extra_args):
    _bootstrap(app_layout)
    _exec_script(app_layout, "train.py", body)
    return _exp(app_layout.app_name, action="run", extra_args=list(extra_args),
                run_cmd=[_PY, "train.py"])


def _runs(app_layout):
    storage = _storage(app_layout)
    return {m["verstr"]: m for m in storage.list_snapshots(app_layout.app_name)}


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _only_run(app_layout):
    (verstr,) = _runs(app_layout)
    return verstr


def test_script_with_start_run_under_vmn_exp_run_is_one_run_with_its_metrics(app_layout):
    assert _run(app_layout, TRAIN) == 0

    verstr = _only_run(app_layout)
    assert any(e.get("values", {}).get("loss") == 0.25 for e in _log(app_layout, verstr))


def test_the_record_holds_a_supervisor_stream_and_a_guest_stream(app_layout):
    _run(app_layout, TRAIN)

    verstr = _only_run(app_layout)
    writers = {display_writer(w) for w in
               _storage(app_layout).load_logs_by_writer(app_layout.app_name, verstr)}
    guests = {w for w in writers if w.endswith(GUEST_WRITER_SUFFIX)}
    assert len(writers) == 2 and len(guests) == 1
    assert writers - guests == {w[: -len(GUEST_WRITER_SUFFIX)] for w in guests}


def test_adopted_run_status_and_exit_code_are_the_processs(app_layout):
    body = TRAIN.replace("print('SDK_RUN', run.id)\n", "run.finish(0)\nsys.exit(3)\n")

    assert _run(app_layout, body) == 3

    state = load_run_state(_storage(app_layout), app_layout.app_name, _only_run(app_layout))
    assert state["exit_code"] == 3 and derive_status(state, now=datetime.now(timezone.utc)) == "failed"


def test_exactly_one_run_entry_and_one_final_state_are_recorded(app_layout):
    _run(app_layout, TRAIN)

    verstr = _only_run(app_layout)
    assert len([e for e in _log(app_layout, verstr) if e["type"] == "run"]) == 1
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["runner"] == RUNNER_CLI and state["state"] == "finished"


def test_adopted_run_ends_fully_compacted(app_layout):
    body = (
        "import os, time\n"
        "with open(os.environ['VMN_METRICS_FILE'], 'a') as f:\n"
        "    f.write('step=0 from_file=1\\n')\n"
        "time.sleep(1.5)\n"
    ) + TRAIN

    assert _run(app_layout, body) == 0

    verstr = _only_run(app_layout)
    log = _log(app_layout, verstr)
    assert any("from_file" in e.get("values", {}) for e in log)
    assert record_compacted(_storage(app_layout), app_layout.app_name, verstr) is True


def test_second_plain_start_run_in_the_script_nests_under_the_run(app_layout):
    body = TRAIN + "with start_run() as second:\n    pass\nprint('SECOND', second.id)\n"

    _run(app_layout, body)

    runs = _runs(app_layout)
    (outer,) = [v for v, m in runs.items() if not m.get("parent")]
    assert len(runs) == 2
    assert [m["parent"] for v, m in runs.items() if v != outer] == [outer]


def test_no_adopt_flag_keeps_wrapper_plus_child(app_layout):
    _run(app_layout, TRAIN, "--no-adopt")

    runs = _runs(app_layout)
    (outer,) = [v for v, m in runs.items() if not m.get("parent")]
    assert [m["parent"] for v, m in runs.items() if v != outer] == [outer]


def test_workers_spawned_by_a_shell_launcher_all_nest_and_none_adopts(app_layout):
    _bootstrap(app_layout)
    _exec_script(app_layout, "train.py", TRAIN)
    launcher = f"{_PY} train.py & {_PY} train.py; wait"

    assert _exp(app_layout.app_name, action="run", run_cmd=["sh", "-c", launcher]) == 0

    runs = _runs(app_layout)
    (outer,) = [v for v, m in runs.items() if not m.get("parent")]
    assert len(runs) == 3
    assert {m["parent"] for v, m in runs.items() if v != outer} == {outer}
