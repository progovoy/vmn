"""The submission hint: once ``vmn-exp create``/``run`` claimed a run, the past
runs most like it on stderr — only from a warm index cache, within its time
budget, never for inner runs or when turned off, and never failing the run."""
import os
import sys

import pytest
from exp_helpers import (
    _bootstrap,
    _exp,
    _init_app,
    _run_vmn_init,
    _stamp_app,
    _storage,
    extract_dev_verstr,
)
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.cli import similar_hint

TRAIN = "def train_step():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return {}\n"
HEAD = "1 similar run: best val_loss=0.3 — "


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)
    # Machine speed must not decide these tests; the budget test fakes the clock.
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 60.0)


def _prior_and_dirty_tree(app_layout, bootstrap=_bootstrap):
    """A past run that changed train_step (by alice, val_loss 0.3), and a tree changing it too."""
    bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN.format("a"))
    prior = seed(_storage(app_layout), app_layout.app_name, verstr(1, commit="0000000"),
                 changes=features(["train.py"], [TRAIN_STEP], author="alice@x.io"),
                 metrics={"val_loss": 0.3}, goal=("val_loss", "min"), exit_code=0)
    with open(os.path.join(app_layout.repo_path, "train.py"), "w") as f:
        f.write(TRAIN.format("b"))
    return prior


def _warm(app_layout):
    assert _exp(app_layout.app_name, action="list") == 0


def _create(app_layout, capfd, *args):
    capfd.readouterr()
    assert _exp(app_layout.app_name, extra_args=list(args)) == 0
    return capfd.readouterr()


def _hints(err):
    return [line for line in err.splitlines() if "similar run" in line]


def test_create_names_the_closest_past_run_on_stderr(app_layout, capfd):
    prior = _prior_and_dirty_tree(app_layout)
    _warm(app_layout)

    out = _create(app_layout, capfd)

    [line] = _hints(out.err)
    assert line.startswith(HEAD + f"{prior} by alice@x.io, ")
    assert "train_step" in line
    # stdout still ends with the new verstr, and carries no hint.
    assert extract_dev_verstr(out.out) and not _hints(out.out)


def test_run_prints_the_hint_before_supervising_the_child(app_layout, capfd):
    prior = _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    capfd.readouterr()

    code = _exp(app_layout.app_name, action="run",
                run_cmd=[sys.executable, "-c", "print('child ran')"])

    out = capfd.readouterr()
    assert code == 0, out.err
    [line] = _hints(out.err)
    assert line.startswith(HEAD + prior)


def test_no_hint_while_the_index_cache_is_cold(app_layout, capfd):
    _prior_and_dirty_tree(app_layout)
    assert _hints(_create(app_layout, capfd).err) == []


def test_no_hint_with_no_similar(app_layout, capfd):
    _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    assert _hints(_create(app_layout, capfd, "--no-similar").err) == []


def _hint_off(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    app_layout.write_conf(params["app_conf_path"], experiment={"similar": {"hint": False}})
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_no_hint_when_the_conf_turns_it_off(app_layout, capfd):
    _prior_and_dirty_tree(app_layout, bootstrap=_hint_off)
    _warm(app_layout)
    assert _hints(_create(app_layout, capfd).err) == []


def test_no_hint_for_an_inner_run(app_layout, capfd, monkeypatch):
    prior = _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    assert _hints(_create(app_layout, capfd, "--parent", prior).err) == []
    monkeypatch.setenv("VMN_EXPERIMENT_ID", prior)
    assert _hints(_create(app_layout, capfd).err) == []


def test_no_hint_past_the_time_budget(app_layout, capfd, monkeypatch):
    _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 0.3)
    ticks = iter(range(0, 10000, 1))  # one second per reading
    monkeypatch.setattr(similar_hint, "_clock", lambda: float(next(ticks)))
    assert _hints(_create(app_layout, capfd).err) == []


def test_a_failing_hint_never_fails_the_run(app_layout, capfd, monkeypatch):
    _prior_and_dirty_tree(app_layout)
    _warm(app_layout)

    def broken(*args, **kwargs):
        raise RuntimeError("index on fire")

    monkeypatch.setattr(similar_hint, "search", broken)
    out = _create(app_layout, capfd)
    assert _hints(out.err) == [] and "index on fire" not in out.err
