"""A failed SDK run records its exception in the final ``run_state.yml``."""
import os
import subprocess
import textwrap

import pytest
import yaml
from exp_helpers import _PY, _SRC_PATH
from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import run as run_module
from vmn_exp.sdk import start_run
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.snapshot import open_storage

VERSTR = "0.0.1-dev.abc1234.def5678"


@pytest.fixture
def container(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {
                "verstr": VERSTR,
                "app_name": "trainer",
                "base_version": "0.0.1",
                "base_commit": "abc1234" * 5 + "abcde",
                "branch": "main",
            }
        )
    )
    store = tmp_path / "store"
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_WORKING_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(image)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store))
    return store


def _storage(store):
    return open_storage(root=str(store), area="runs")


def _state(store, run_id):
    return load_run_state(_storage(store), "trainer", run_id)


def _errors(store, run_id):
    log = _storage(store).load_merged_log("trainer", run_id)
    return [e for e in log if e.get("type") == "error"]


class TrainingDiverged(Exception):
    pass


def test_context_manager_records_the_exception(container):
    with pytest.raises(TrainingDiverged):
        with start_run() as run:
            raise TrainingDiverged("loss is nan")

    error = _state(container, run.id)["error"]
    assert error["type"] == f"{__name__}.TrainingDiverged"
    assert error["message"] == "loss is nan"
    assert error["source"] == "exception"
    assert "raise TrainingDiverged" in error["traceback"]
    (entry,) = _errors(container, run.id)
    assert entry["exception"] == "TrainingDiverged"
    assert entry["message"] == "loss is nan"
    assert "raise TrainingDiverged" in entry["traceback"]


def test_clean_run_records_no_error(container):
    with start_run() as run:
        pass
    assert "error" not in _state(container, run.id)
    assert _errors(container, run.id) == []


def test_system_exit_records_no_error(container):
    with pytest.raises(SystemExit):
        with start_run() as run:
            raise SystemExit(3)
    state = _state(container, run.id)
    assert state["exit_code"] == 3
    assert "error" not in state


def test_finish_with_an_exception(container):
    run = start_run()
    run.finish(exit_code=2, error=ValueError("bad config"))

    state = _state(container, run.id)
    assert state["exit_code"] == 2
    assert state["error"]["type"] == "ValueError"
    assert state["error"]["message"] == "bad config"
    assert _errors(container, run.id)[0]["message"] == "bad config"


def test_finish_with_a_message(container):
    run = start_run()
    run.finish(exit_code=1, error="gave up after 3 retries")

    assert _state(container, run.id)["error"] == {
        "message": "gave up after 3 retries", "source": "user",
    }


def test_finish_with_an_error_and_exit_code_zero_still_records_it(container):
    run = start_run()
    run.finish(error="partial results")
    state = _state(container, run.id)
    assert state["exit_code"] == 0
    assert state["error"]["message"] == "partial results"


def test_a_failing_error_conversion_never_breaks_finalization(container, monkeypatch):
    def boom(exc):
        raise RuntimeError("formatter broke")

    monkeypatch.setattr(run_module, "error_from_exception", boom)
    run = start_run()
    run.finish(exit_code=1, error=ValueError("x"))

    state = _state(container, run.id)
    assert state["state"] == "finished"
    assert state["exit_code"] == 1
    assert run not in run_module._OPEN_RUNS


def test_noop_run_accepts_an_error():
    assert NoOpRun("app").finish(exit_code=1, error=ValueError("x")) is None
    assert NoOpRun("app").finish(1, "message") is None


def test_uncaught_exception_outside_a_context_manager_is_recorded(container, tmp_path):
    script = tmp_path / "train.py"
    script.write_text(textwrap.dedent(
        """
        from vmn_exp.sdk import start_run
        run = start_run()
        print(run.id, flush=True)
        raise KeyError("lr")
        """
    ))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (_SRC_PATH, env.get("PYTHONPATH")) if p)
    proc = subprocess.run(
        [_PY, str(script)], env=env, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 1, proc.stderr
    run_id = proc.stdout.split()[0]

    state = _state(container, run_id)
    assert state["exit_code"] == run_module.ABANDONED_EXIT_CODE
    assert state["error"]["type"] == "KeyError"
    assert state["error"]["message"] == "'lr'"
    assert 'raise KeyError("lr")' in state["error"]["traceback"]
    assert _errors(container, run_id)[0]["exception"] == "KeyError"
