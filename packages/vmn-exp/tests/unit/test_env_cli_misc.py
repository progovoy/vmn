"""The similar-runs hint, ``vmn-exp run`` under VMN_MODE=disabled and the
diag allocator report read the Env they are given (plan 44 G12)."""
import argparse
import os

import pytest

from fakes.env import FakeEnv
from vmn_exp.cli import run_disabled, similar_hint
from vmn_exp.ui.diag import gc_pauses


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    monkeypatch.setenv("VMN_EXPERIMENT_ID", "0.0.1-dev.process")
    monkeypatch.delenv("VMN_MODE", raising=False)


def test_the_hint_is_skipped_inside_a_run_the_given_env_names():
    no_flags = argparse.Namespace()

    assert similar_hint._wanted(no_flags, {}, FakeEnv()) is True
    assert similar_hint._wanted(no_flags, {}, FakeEnv({"VMN_EXPERIMENT_ID": "0.0.1-dev.x"})) is False


def test_a_disabled_run_execs_its_command_with_the_given_env(monkeypatch, tmp_path):
    execs = []
    monkeypatch.setattr(os, "chdir", lambda path: None)
    monkeypatch.setattr(os, "execvpe", lambda file, argv, env: execs.append(env))
    env = FakeEnv({"VMN_MODE": "disabled", "VMN_WORKING_DIR": str(tmp_path), "GIVEN": "1"})

    assert run_disabled.exec_if_disabled(argparse.Namespace(run_cmd=["true"]), env) == 0

    (child_env,) = execs
    assert child_env["GIVEN"] == "1" and child_env["VMN_METRICS_FILE"] == os.devnull
    assert "VMN_EXPERIMENT_ID" not in child_env


def test_allocator_info_has_no_environment_default():
    with pytest.raises(TypeError):
        gc_pauses.allocator_info()
    assert gc_pauses.allocator_info(FakeEnv(), free_threaded=False)["name"] == "pymalloc"
