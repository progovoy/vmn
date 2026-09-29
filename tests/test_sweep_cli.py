"""``vmn-exp sweep create|agent|status``: the server-less sweep controller."""
import json
import os
import subprocess
import textwrap

import pytest
import yaml

from helpers import _PY, _SRC_PATH, _bootstrap, _storage, extract_dev_verstr
from version_stamp.core.logging import reset_logger
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.core.status import load_run_state
from vmn_exp.core.sweep.claims import list_claims
from vmn_exp.sdk.reader import list_runs

TRAIN = textwrap.dedent(
    """
    import json, os, sys, time
    params = json.loads(os.environ["VMN_SWEEP_PARAMS"])
    x = params["x"]
    assert sys.argv[1:] == ["--x=%s" % x], sys.argv
    assert os.environ["VMN_SWEEP_TRIAL"].isdigit()
    if os.path.exists(os.path.join(os.environ["FAIL_DIR"], "fail_%s" % x)):
        sys.exit(1)
    slow = x >= 10
    with open(os.environ["VMN_METRICS_FILE"], "a") as f:
        for step in range(1, (60 if slow else 4) + 1):
            f.write("step=%d loss=%s\\n" % (step, x + 1.0 / step))
            f.flush()
            time.sleep(0.25 if slow else 0.0)
    """
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SWEEP_PARAMS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FAIL_DIR", str(tmp_path))


def _vmn_exp(*argv):
    reset_logger()
    return vmn_exp_run(list(argv))[0]


def _write_spec(tmp_path, **overrides):
    train = tmp_path / "train.py"
    train.write_text(TRAIN)
    spec = {
        "method": "grid",
        "metric": {"name": "loss", "goal": "minimize"},
        "parameters": {"x": {"values": [3, 1, 2]}},
        "program": str(train),
    }
    spec.update(overrides)
    path = tmp_path / "sweep.yml"
    path.write_text(yaml.safe_dump(spec))
    return str(path)


def _create(app_layout, tmp_path, capsys, **overrides):
    _bootstrap(app_layout)
    capsys.readouterr()
    assert _vmn_exp("sweep", "create", app_layout.app_name, "-f",
                    _write_spec(tmp_path, **overrides), "--name", "sw") == 0
    sweep = extract_dev_verstr(capsys.readouterr().out)
    assert sweep
    return sweep


def _trials(app_layout, sweep):
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout), use_index=False)
    return sorted(
        (r for r in rows if r.get("parent") == sweep),
        key=lambda r: (int(r["tags"]["sweep_trial"]), int(r["tags"]["sweep_attempt"])),
    )


def _status(app_layout, sweep, capsys):
    capsys.readouterr()
    assert _vmn_exp("sweep", "status", app_layout.app_name, sweep, "--json") == 0
    out = capsys.readouterr().out
    return json.loads(out[out.index("{"):])


def test_create_records_the_normalized_spec_on_an_outer_run(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys)
    meta = _storage(app_layout).load_metadata(app_layout.app_name, sweep)
    assert meta["name"] == "sw"
    assert meta["sweep"]["method"] == "grid"
    assert meta["sweep"]["metric"] == {"name": "loss", "goal": "min"}


def test_create_rejects_an_invalid_spec(app_layout, tmp_path):
    _bootstrap(app_layout)
    path = _write_spec(tmp_path, method="hill-climb")
    assert _vmn_exp("sweep", "create", app_layout.app_name, "-f", path) != 0


def test_agent_runs_every_grid_trial_as_an_inner_job(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0

    trials = _trials(app_layout, sweep)
    assert [t["params"]["x"] for t in trials] == [3, 1, 2]  # values in spec order
    assert all(t["status"] == "succeeded" for t in trials)
    assert all(t["kind"] == "inner" for t in trials)
    assert trials[0]["metrics"]["loss"] == pytest.approx(3.25)

    rows = list_runs(app_layout.app_name, storage=_storage(app_layout),
                     query="params.x = 2", use_index=False)
    assert [r["verstr"] for r in rows] == [trials[2]["verstr"]]
    outer = next(r for r in list_runs(app_layout.app_name, storage=_storage(app_layout),
                                      use_index=False) if r["verstr"] == sweep)
    assert outer["kind"] == "outer"


def test_agent_count_limits_the_trials_it_runs(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep, "--count", "2") == 0
    assert len(_trials(app_layout, sweep)) == 2
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    assert len(_trials(app_layout, sweep)) == 3


def test_run_cap_ends_the_sweep(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys, run_cap=2)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    assert len(_trials(app_layout, sweep)) == 2


def test_agent_command_after_double_dash_overrides_the_spec(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys, run_cap=1)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep, "--",
                    _PY, str(tmp_path / "train.py"), "--x=${x}") == 0
    [trial] = _trials(app_layout, sweep)
    assert trial["status"] == "succeeded"
    state = load_run_state(_storage(app_layout), app_layout.app_name, trial["verstr"])
    assert state["command"][-1] == "--x=3"


def test_status_reports_counts_and_the_best_trial(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys)
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    status = _status(app_layout, sweep, capsys)
    assert status["counts"] == {"succeeded": 3}
    assert status["best"]["params"] == {"x": 1}
    assert status["best"]["value"] == pytest.approx(1.25)
    assert status["metric"] == {"name": "loss", "goal": "min"}


def test_failed_trials_are_only_rerun_with_retry_failed(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys)
    (tmp_path / "fail_1").write_text("")
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    assert _status(app_layout, sweep, capsys)["counts"] == {"succeeded": 2, "failed": 1}

    (tmp_path / "fail_1").unlink()
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    assert len(_trials(app_layout, sweep)) == 3  # nothing left, nothing retried

    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep, "--retry-failed") == 0
    trials = _trials(app_layout, sweep)
    assert len(trials) == 4
    assert [(t["tags"]["sweep_trial"], t["tags"]["sweep_attempt"]) for t in trials] == [
        ("0", "0"), ("1", "0"), ("1", "1"), ("2", "0"),
    ]
    assert trials[2]["params"] == {"x": 1}
    assert _status(app_layout, sweep, capsys)["counts"] == {"succeeded": 3}


def test_median_rule_stops_a_trial_behind_the_others(app_layout, tmp_path, capsys):
    sweep = _create(
        app_layout, tmp_path, capsys,
        parameters={"x": {"values": [0, 1, 10]}},
        early_terminate={"type": "median", "min_iter": 2, "check_interval_sec": 0.2},
    )
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0

    fast0, fast1, slow = _trials(app_layout, sweep)
    assert fast0["end_reason"] is None
    assert slow["end_reason"] == "stopped"
    assert "stopped_early" not in slow["tags"]
    assert slow["status"] == "succeeded"
    state = load_run_state(_storage(app_layout), app_layout.app_name, slow["verstr"])
    assert state["end_reason"] == "stopped"
    assert state["duration_sec"] < 10  # 60 steps * 0.25s had it run out
    status = _status(app_layout, sweep, capsys)
    assert status["stopped_early"] == 1


def test_two_agent_processes_never_run_the_same_trial(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys,
                    parameters={"x": {"values": list(range(8))}})
    env = dict(os.environ, PYTHONPATH=_SRC_PATH, VMN_WORKING_DIR=app_layout.repo_path)
    agents = [
        subprocess.Popen(
            [_PY, "-m", "vmn_exp.cli", "sweep", "agent", app_layout.app_name, sweep],
            cwd=app_layout.repo_path, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for _ in range(2)
    ]
    outputs = [a.communicate(timeout=300)[0] for a in agents]
    assert [a.returncode for a in agents] == [0, 0], outputs

    trials = _trials(app_layout, sweep)
    assert sorted(t["params"]["x"] for t in trials) == list(range(8))
    claims = list_claims(_storage(app_layout), app_layout.app_name, sweep)
    assert sorted(c["trial"] for c in claims) == list(range(8))
    assert len({c["agent"] for c in claims}) >= 1
