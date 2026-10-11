"""The submission hint: once ``vmn-exp create``/``run`` claimed a run, the past
runs most like it on stderr — only from a warm index cache, within its time
budget, never for inner runs or when turned off, and never failing the run."""
import argparse
import os
import sys
import threading

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


def _never(*args, **kwargs):
    raise AssertionError("the hint listed the store")


def test_the_hint_reads_the_index_cache_and_never_lists_the_store(app_layout, capfd,
                                                                    monkeypatch):
    # A remote store's refresh reads on a thread pool that the process exit
    # waits for, budget or not: the hint must not start one.
    from vmn_exp.storage.local import LocalSnapshotStorage

    prior = _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    new = extract_dev_verstr(_create(app_layout, capfd, "--no-similar").out)
    monkeypatch.setattr(LocalSnapshotStorage, "is_remote", lambda self: True)
    for listing in ("list_record_names", "list_files", "list_snapshots"):
        monkeypatch.setattr(LocalSnapshotStorage, listing, _never)

    similar_hint.print_hint(_storage(app_layout), app_layout.app_name, new,
                            argparse.Namespace(), {})

    [line] = _hints(capfd.readouterr().err)
    assert line.startswith(HEAD + prior)


def _record_index_loads(monkeypatch):
    loads = []

    def follower(cls, *args):
        loads.append(args)
        raise AssertionError("the hint loaded the index")

    monkeypatch.setattr(similar_hint.ExperimentIndex, "follower", classmethod(follower))
    return loads


def test_no_hint_and_no_index_load_past_the_runs_it_can_search_in_budget(app_layout, capfd,
                                                                         monkeypatch):
    # Waiting at most the budget is not enough: loading a big index past it
    # would still cost the command its time and memory.
    _prior_and_dirty_tree(app_layout)
    seed(_storage(app_layout), app_layout.app_name, verstr(2, commit="0000000"))
    _warm(app_layout)
    monkeypatch.setattr(similar_hint, "MAX_INDEXED_RUNS", 1)
    loads = _record_index_loads(monkeypatch)

    assert _hints(_create(app_layout, capfd).err) == []
    assert loads == []


def test_the_hint_searches_an_index_of_up_to_its_runs_cap(app_layout, capfd, monkeypatch):
    prior = _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    monkeypatch.setattr(similar_hint, "MAX_INDEXED_RUNS", 1)

    [line] = _hints(_create(app_layout, capfd).err)
    assert line.startswith(HEAD + prior)


def test_a_hint_past_its_budget_stops_before_searching(app_layout, capfd, monkeypatch):
    _prior_and_dirty_tree(app_layout)
    _warm(app_layout)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 0.01)
    command_done, searched = threading.Event(), []
    load = similar_hint._cached_snapshot

    def load_until_the_command_is_done(*args, **kwargs):
        command_done.wait(30)
        return load(*args, **kwargs)

    monkeypatch.setattr(similar_hint, "_cached_snapshot", load_until_the_command_is_done)
    monkeypatch.setattr(similar_hint, "search", lambda *a, **k: searched.append(a) or [])

    assert _hints(_create(app_layout, capfd).err) == []
    command_done.set()
    for thread in threading.enumerate():
        if thread.name == "vmn-similar-hint":
            thread.join(30)
    assert searched == []
