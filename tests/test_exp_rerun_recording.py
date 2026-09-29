"""What a rerun needs recorded: the runner and repo-relative cwd of every run,
``rerun_of`` as a row/query/detail field, and finding a snapshot's code object.
"""
import argparse
import os

import pytest
from helpers import _PY, _bootstrap, _exec_script, _exp, _storage

from vmn_exp.core.code_store import code_key, find_code_key, store_code
from vmn_exp.core.fold import fold_row, new_fold
from vmn_exp.core.log import experiment_row
from vmn_exp.core.query import filter_rows
from vmn_exp.core.rerun import RUNNER_CLI, RUNNER_SDK
from vmn_exp.core.status import load_run_state
from vmn_exp.snapshot import LocalSnapshotStorage

META = {"verstr": "0.0.1-dev.a.r2", "timestamp": "2026-01-01T00:00:00Z"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA"):
        monkeypatch.delenv(key, raising=False)


# -- code store ----------------------------------------------------------------

def _store(storage, key):
    store_code(storage, "app", key, {}, {"has_working_tree_patch": False})


def test_find_code_key_by_code_verstr_prefix(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    _store(storage, code_key("0.0.1-dev.abc.fff", "f" * 64))
    _store(storage, code_key("0.0.1-dev.abc.fffx", "e" * 64))
    assert find_code_key(storage, "app", "0.0.1-dev.abc.fff") == code_key(
        "0.0.1-dev.abc.fff", "f" * 64
    )


def test_find_code_key_none_when_missing_or_ambiguous(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path))
    assert find_code_key(storage, "app", "v") is None
    _store(storage, code_key("v", "a" * 64))
    _store(storage, code_key("v", "b" * 64))
    assert find_code_key(storage, "app", "v") is None


# -- row / query / detail ----------------------------------------------------------

def test_row_carries_rerun_of():
    row = fold_row(1, dict(META, rerun_of="0.0.1-dev.a"), new_fold())
    assert row["rerun_of"] == "0.0.1-dev.a"
    assert experiment_row(1, META, [])["rerun_of"] is None


def test_query_filters_on_rerun_of_and_null():
    rows = [
        experiment_row(1, dict(META, verstr="a"), []),
        experiment_row(2, dict(META, verstr="b", rerun_of="a"), []),
    ]
    assert [r["verstr"] for r in filter_rows(rows, 'rerun_of = "a"')] == ["b"]
    assert [r["verstr"] for r in filter_rows(rows, "rerun_of = null")] == ["a"]


def test_detail_returns_rerun_of(tmp_path):
    from vmn_exp.ui.readers.experiment_detail import experiment_detail

    storage = LocalSnapshotStorage(str(tmp_path))
    storage.save("app", "b", dict(META, verstr="b", rerun_of="a"), {})
    storage.append_log_entry("app", "b", "w", {"timestamp": META["timestamp"], "type": "create"})
    detail, err = experiment_detail(storage, "app", "b")
    assert err is None
    assert detail["rerun_of"] == "a"


def test_webui_query_suggest_knows_rerun_of():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "packages", "vmn-exp", "webui", "src", "util", "querySuggest.ts")
    with open(path) as f:
        source = f.read()
    fields = source.split("ROW_FIELDS = [", 1)[1].split("]", 1)[0]
    assert '"rerun_of"' in fields and '"forked_from"' in fields


# -- run state: vmn-exp run ----------------------------------------------------------

def _latest(app_layout):
    storage = _storage(app_layout)
    return storage, sorted(storage.list_record_names(app_layout.app_name))[-1]


def _latest_state(app_layout):
    storage, verstr = _latest(app_layout)
    return load_run_state(storage, app_layout.app_name, verstr)


def _created_run(app_layout):
    """``(storage, verstr, args)`` of a fresh, never-run experiment."""
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name) == 0
    args = argparse.Namespace(note=None, capture_output=False, system_metrics=False)
    return _latest(app_layout) + (args,)


def _job(app_layout):
    return _exec_script(app_layout, "job.py", "import sys\nsys.exit(0)\n")


def test_run_state_cwd_is_dot_at_repo_root(app_layout):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, _job(app_layout)]) == 0
    state = _latest_state(app_layout)
    assert state["runner"] == RUNNER_CLI
    assert state["cwd"] == "."


def test_run_state_records_runner_and_repo_relative_cwd(app_layout, monkeypatch):
    _bootstrap(app_layout)
    job = _job(app_layout)
    sub = os.path.join(app_layout.repo_path, "src", "pkg")
    os.makedirs(sub)
    monkeypatch.setenv("VMN_WORKING_DIR", sub)
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, job]) == 0
    state = _latest_state(app_layout)
    assert state["runner"] == RUNNER_CLI
    assert state["cwd"] == "src/pkg"


def test_supervision_cwd_param_overrides_child_cwd(app_layout, tmp_path):
    from vmn_exp.cli.run import _Supervision

    storage, verstr, args = _created_run(app_layout)
    root = tmp_path / "work"
    child_dir = root / "src"
    child_dir.mkdir(parents=True)
    probe = "import os; open('where.txt', 'w').write(os.getcwd())"

    sup = _Supervision(storage, app_layout.app_name, verstr, args,
                       cwd=str(child_dir), root=str(root))
    assert sup.run([_PY, "-c", probe]) == 0

    where = (child_dir / "where.txt").read_text()
    assert os.path.realpath(where) == os.path.realpath(str(child_dir))
    state = load_run_state(storage, app_layout.app_name, verstr)
    assert state["cwd"] == "src"
    assert state["runner"] == RUNNER_CLI


def test_supervision_without_root_records_null_cwd(app_layout):
    from vmn_exp.cli.run import _Supervision

    storage, verstr, args = _created_run(app_layout)
    assert _Supervision(storage, app_layout.app_name, verstr, args).run([_PY, "-c", "0"]) == 0
    assert load_run_state(storage, app_layout.app_name, verstr)["cwd"] is None


def test_supervision_extra_env_none_removes_the_variable(app_layout, tmp_path, monkeypatch):
    from vmn_exp.cli.run import _Supervision

    storage, verstr, args = _created_run(app_layout)
    monkeypatch.setenv("VMN_RESUME_RUN_ID", "stale")
    probe = "import os; open('env.txt', 'w').write(repr(os.environ.get('VMN_RESUME_RUN_ID')))"
    sup = _Supervision(storage, app_layout.app_name, verstr, args,
                       extra_env={"VMN_RESUME_RUN_ID": None}, cwd=str(tmp_path))
    assert sup.run([_PY, "-c", probe]) == 0
    assert (tmp_path / "env.txt").read_text() == "None"


# -- run state: SDK ------------------------------------------------------------------

def test_sdk_run_state_records_runner_sdk(app_layout, monkeypatch):
    from vmn_exp.sdk import start_run

    _bootstrap(app_layout)
    sub = os.path.join(app_layout.repo_path, "src")
    os.makedirs(sub)
    monkeypatch.chdir(sub)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
    state = load_run_state(_storage(app_layout), app_layout.app_name, verstr)
    assert state["runner"] == RUNNER_SDK
    assert state["cwd"] == "src"
