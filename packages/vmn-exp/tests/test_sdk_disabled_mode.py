"""``VMN_MODE=disabled`` / ``start_run(mode="disabled")``: record nothing.

A kill switch for CI, unit tests of training code and debugging sessions: the
script keeps calling the SDK, but no snapshot, run record, code object or
heartbeat is created, and no git checkout is needed.
"""
import importlib
import os
import threading

import pytest
from exp_helpers import _bootstrap, _storage

from vmn_exp.sdk import NoOpRun, Run, autolog, autolog_disable, current_run, start_run
from vmn_exp.sdk import import_hooks

# The package re-exports the autolog() function under the module's name.
autolog_module = importlib.import_module("vmn_exp.sdk.autolog")

_ENV_KEYS = (
    "VMN_MODE",
    "RANK",
    "LOCAL_RANK",
    "WORLD_SIZE",
    "SLURM_PROCID",
    "VMN_EXPERIMENT_ID",
    "VMN_APP_NAME",
    "VMN_RESUME_RUN_ID",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def outside_git(tmp_path, monkeypatch):
    """A cwd with no git checkout and an experiment dir inside it."""
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "store"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _heartbeat_threads():
    return [t for t in threading.enumerate() if t.name == "vmn-heartbeat"]


def test_start_run_disabled_returns_noop_and_writes_nothing(outside_git):
    with start_run("app", params={"lr": 0.1}, mode="disabled") as run:
        assert isinstance(run, NoOpRun)
        run.log_metric("loss", 1.0, step=1)
    run.finish()

    # No run record, no vmn-code/<app> code object: the store is never created.
    assert list(outside_git.rglob("*")) == []


def test_env_disabled_returns_noop(outside_git, monkeypatch):
    monkeypatch.setenv("VMN_MODE", "disabled")

    run = start_run("app")

    assert isinstance(run, NoOpRun)
    assert list(outside_git.rglob("*")) == []


def test_explicit_enabled_overrides_env(app_layout, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_MODE", "disabled")

    with start_run(app_layout.app_name, mode="enabled") as run:
        assert isinstance(run, Run)

    verstrs = [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]
    assert verstrs == [run.id]


@pytest.mark.parametrize("mode", ["online", "offline", "DISABLED ", 0])
def test_invalid_mode_raises(outside_git, mode):
    with pytest.raises(ValueError):
        start_run("app", mode=mode)


def test_disabled_run_has_disabled_true_and_id_none(outside_git):
    run = start_run("app", mode="disabled")

    assert run.disabled is True
    assert run.id is None
    assert run.app_name == "app"
    assert Run.disabled is False
    assert NoOpRun("app").disabled is False


def test_disabled_does_not_consume_resume_env(outside_git, monkeypatch):
    monkeypatch.setenv("VMN_RESUME_RUN_ID", "some-run")

    start_run("app", mode="disabled")

    assert os.environ["VMN_RESUME_RUN_ID"] == "some-run"


def test_current_run_is_none_under_disabled(outside_git):
    with start_run("app", mode="disabled"):
        assert current_run() is None
        assert not _heartbeat_threads()
    assert "VMN_EXPERIMENT_ID" not in os.environ


def test_every_run_method_is_a_noop_under_disabled(outside_git):
    run = start_run("app", mode="disabled")

    assert run.log_metric("loss", 1.0, step=1) is None
    assert run.log_metrics({"acc": 0.5}) is None
    assert run.log_params({"seed": 1}) is None
    assert run.log_note("hi") is None
    assert run.log_artifact("does-not-exist.bin") is None
    assert run.log_input("s3://bucket/data") is None
    assert run.set_tag("k", "v") is None
    assert run.set_tags({"k": "v"}) is None
    assert run.log_dict({"a": 1}, "a.json") is None
    assert run.log_text("x", "x.txt") is None
    assert run.define_metric("loss", goal="minimize") is None
    assert run.finish() is None
    assert list(outside_git.rglob("*")) == []


def test_autolog_under_env_disabled_patches_nothing(monkeypatch):
    patched, hooked = [], []
    monkeypatch.setattr(autolog_module, "_patch_framework", lambda *a: patched.append(a))
    monkeypatch.setattr(import_hooks, "when_imported", lambda *a: hooked.append(a))
    monkeypatch.setenv("VMN_MODE", "disabled")

    try:
        autolog()
    finally:
        autolog_disable()

    assert patched == [] and hooked == []


def test_disabled_on_secondary_rank_also_noop(outside_git, monkeypatch):
    monkeypatch.setenv("RANK", "1")

    run = start_run("app", mode="disabled")

    assert isinstance(run, NoOpRun)
    assert run.disabled is True
