"""``vmn-exp similar <app> [-v <ref> | --latest]``: the past runs most like a
run — or, with no ref, like the current working tree, before any run exists.
Read-only and lock-free; one line per result, or ``--json`` items."""
import json
import os
import subprocess

from exp_helpers import _PY, _SRC_PATH, _bootstrap, _exp, _storage, cli_module
from filelock import FileLock
from similar_seed import TRAIN_STEP, features, seed, verstr

TRAIN = "def train_step():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return {}\n"
ITEM_KEYS = {"app", "verstr", "name", "score", "reasons", "signals", "group_size", "author",
             "timestamp", "status", "goal", "note", "intent", "features"}


def _similar(app_layout, capfd, *args):
    capfd.readouterr()
    code = _exp(app_layout.app_name, action="similar", extra_args=list(args))
    return code, capfd.readouterr()


def _items(app_layout, capfd, *args):
    code, out = _similar(app_layout, capfd, "--json", *args)
    assert code == 0, out.err
    return json.loads(out.out)


def _verstrs(items):
    return [item["verstr"] for item in items]


def _train_step_run(storage, app, n, **kwargs):
    kwargs.setdefault("changes", features(["train.py"], [TRAIN_STEP]))
    return seed(storage, app, verstr(n), **kwargs)


def test_no_ref_compares_the_working_tree_and_finds_the_run_that_changed_the_same_function(
        app_layout, capfd):
    _bootstrap(app_layout)
    app = app_layout.app_name
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN.format("a"))
    storage = _storage(app_layout)
    match = _train_step_run(storage, app, 1)
    seed(storage, app, verstr(2), changes=features(["data.py"], ["data.py::load"]))
    with open(os.path.join(app_layout.repo_path, "train.py"), "w") as f:
        f.write(TRAIN.format("b"))

    items = _items(app_layout, capfd)

    assert items[0]["verstr"] == match
    assert any("train_step" in reason for reason in items[0]["reasons"])
    assert verstr(2) not in _verstrs(items)


def test_a_run_target_leaves_out_itself_its_reruns_and_its_sweep(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    outer = seed(storage, app, verstr(1))
    trial = _train_step_run(storage, app, 2, parent=outer)
    _train_step_run(storage, app, 3, parent=outer)
    _train_step_run(storage, app, 4, code=trial)  # a rerun of the trial: its code and params
    other = _train_step_run(storage, app, 5)

    assert _verstrs(_items(app_layout, capfd, "-v", trial)) == [other]


def test_latest_targets_the_newest_run(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    first = _train_step_run(storage, app, 1, ts="2026-01-01T00:00:00Z")
    _train_step_run(storage, app, 2, ts="2026-01-02T00:00:00Z")
    assert _verstrs(_items(app_layout, capfd, "--latest")) == [first]


def test_query_narrows_the_candidates(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    target = _train_step_run(storage, app, 1)
    fast = _train_step_run(storage, app, 2, params={"lr": 0.1})
    _train_step_run(storage, app, 3, params={"lr": 0.001})

    assert _verstrs(_items(app_layout, capfd, "-v", target, "--query", "params.lr > 0.01")) == [fast]
    code, out = _similar(app_layout, capfd, "-v", target, "--query", "params.lr >")
    assert code == 1 and "Invalid --query" in out.err


def test_json_items_carry_what_an_agent_needs_to_rerank(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    target = _train_step_run(storage, app, 1)
    other = _train_step_run(storage, app, 2, name="focal", note="gamma 2",
                            metrics={"val_loss": 0.31}, goal=("val_loss", "min"),
                            intent={"text": "try focal loss", "keywords": ["imbalance"]},
                            exit_code=0)

    [item] = _items(app_layout, capfd, "-v", target)

    assert set(item) == ITEM_KEYS
    assert (item["app"], item["verstr"], item["name"], item["note"]) == (
        app, other, "focal", "gamma 2")
    assert item["status"] == "succeeded"
    assert item["goal"] == {"metric": "val_loss", "goal": "min", "value": 0.31}
    assert item["intent"] == {"text": "try focal loss", "keywords": ["imbalance"]}
    assert item["features"]["changed"]["symbols"] == [TRAIN_STEP]
    assert item["signals"]["symbols"] == 1.0


def test_one_line_per_result_with_its_group_size(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    target = _train_step_run(storage, app, 1)
    code = _train_step_run(storage, app, 2, metrics={"val_loss": 0.5}, goal=("val_loss", "min"),
                           changes=features(["train.py"], [TRAIN_STEP], author="bob@x.io"))
    _train_step_run(storage, app, 3, code=code, metrics={"val_loss": 0.4}, exit_code=1)

    rc, out = _similar(app_layout, capfd, "-v", target)

    assert rc == 0, out.err
    [line] = out.out.splitlines()
    # The group's best run on the goal speaks for both runs of that code.
    assert line.startswith(f"{verstr(3)}  ")
    assert "  failed  val_loss=0.4  — " in line and "train_step" in line
    assert line.endswith("  (+1 run)")


def test_top_caps_the_results(app_layout, capfd):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    target = _train_step_run(storage, app, 1)
    for n in range(2, 6):
        _train_step_run(storage, app, n)
    assert len(_items(app_layout, capfd, "-v", target, "--top", "2")) == 2
    assert len(_items(app_layout, capfd, "-v", target)) == 4
    rc, out = _similar(app_layout, capfd, "-v", target, "--top", "0")
    assert rc == 1 and "--top" in out.err


def test_no_similar_run_is_a_note_on_stderr_and_exit_0(app_layout, capfd):
    _bootstrap(app_layout)
    target = _train_step_run(_storage(app_layout), app_layout.app_name, 1)
    rc, out = _similar(app_layout, capfd, "-v", target)
    assert rc == 0 and out.out == ""
    assert "No similar runs" in out.err
    assert _items(app_layout, capfd, "-v", target) == []


def test_without_fts5_similar_says_so_and_exits_1(app_layout, capfd, monkeypatch):
    from vmn_exp.core import similar_fts

    _bootstrap(app_layout)
    target = _train_step_run(_storage(app_layout), app_layout.app_name, 1)
    monkeypatch.setattr(similar_fts, "_FTS5", [False])
    rc, out = _similar(app_layout, capfd, "-v", target)
    assert rc == 1 and "similar runs need SQLite with FTS5" in out.err
    assert "Traceback" not in out.err


def test_an_unknown_ref_is_an_error(app_layout, capfd):
    _bootstrap(app_layout)
    _train_step_run(_storage(app_layout), app_layout.app_name, 1)
    rc, out = _similar(app_layout, capfd, "-v", verstr(9))
    assert rc == 1 and verstr(9) in out.err


def test_an_empty_ref_is_an_unknown_run_not_the_latest(app_layout, capfd):
    _bootstrap(app_layout)
    app = app_layout.app_name
    _train_step_run(_storage(app_layout), app, 1)
    _train_step_run(_storage(app_layout), app, 2)
    rc, out = _similar(app_layout, capfd, "-v", "", "--json")
    assert rc == 1 and out.out == ""
    assert f"Experiment '' not found for {app}" in out.err


def test_similar_is_read_only_and_never_waits_for_the_repo_lock(app_layout):
    from vmn_exp.cli.experiment import READ_ONLY_ACTIONS
    from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS

    assert "similar" in EXPERIMENT_ACTIONS and "similar" in READ_ONLY_ACTIONS
    _bootstrap(app_layout)
    target = _train_step_run(_storage(app_layout), app_layout.app_name, 1)
    env = dict(os.environ, VMN_WORKING_DIR=app_layout.repo_path, PYTHONPATH=_SRC_PATH)
    argv = ["exp", "similar", app_layout.app_name, "-v", target]
    lock = FileLock(os.path.join(app_layout.repo_path, ".vmn", "vmn.lock"))
    with lock:
        proc = subprocess.run([_PY, "-m", cli_module(argv)] + argv, cwd=app_layout.repo_path,
                              env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def _write(app_layout, name, content):
    with open(os.path.join(app_layout.repo_path, name), "w") as f:
        f.write(content)


def test_runs_created_from_real_trees_find_each_other_by_what_they_changed(app_layout, capfd):
    _bootstrap(app_layout)
    app = app_layout.app_name
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN.format("a"))
    app_layout.write_file_commit_and_push("test_repo_0", "data.py", TRAIN.format("a")
                                          .replace("train_step", "load"))
    _write(app_layout, "train.py", TRAIN.format("b"))
    assert _exp(app) == 0
    trained = _storage(app_layout).list_snapshots(app)[-1]["verstr"]
    subprocess.run(["git", "checkout", "train.py"], cwd=app_layout.repo_path, check=True)
    _write(app_layout, "data.py", TRAIN.format("b").replace("train_step", "load"))
    assert _exp(app) == 0
    subprocess.run(["git", "checkout", "data.py"], cwd=app_layout.repo_path, check=True)
    _write(app_layout, "train.py", TRAIN.format("c"))

    items = _items(app_layout, capfd)

    assert items[0]["verstr"] == trained
    assert items[0]["author"] == "test@test.com"
    assert any("train_step" in reason for reason in items[0]["reasons"])
