"""``vmn-exp rerun``: a run's recorded command, executed again against the
run's own code in a throwaway workspace, recorded as a new linked run."""
import os

import pytest
from helpers import _PY, _bootstrap, _exp, _storage
from rerun_helpers import (
    TRAIN, code_objects, log, meta, metric_values, original_run, read, repo, rerun,
    run_names, worktrees, write,
)

from vmn_exp.core.code_store import code_app
from vmn_exp.core.status import FAILED, derive_status, load_run_state


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def test_rerun_executes_recorded_command_against_original_code(app_layout):
    orig = original_run(app_layout)
    rc, new = rerun(app_layout, orig)
    assert rc == 0
    assert metric_values(app_layout, orig) == [1.0]
    assert metric_values(app_layout, new) == [1.0]
    assert read(app_layout, "value.txt") == "2\n"


def test_rerun_links_rerun_of_shares_code_verstr_and_code_key(app_layout):
    orig = original_run(app_layout)
    _, new = rerun(app_layout, orig)
    source, record = meta(app_layout, orig), meta(app_layout, new)
    assert record["rerun_of"] == orig
    assert record["code_verstr"] == source["code_verstr"]
    assert record["code"] == source["code"]
    assert new.startswith(source["code_verstr"] + ".r")


def test_rerun_uploads_no_new_code_object(app_layout):
    orig = original_run(app_layout)
    before = code_objects(app_layout)
    rerun(app_layout, orig)
    assert code_objects(app_layout) == before


def test_rerun_survives_pruning_original(app_layout):
    orig = original_run(app_layout)
    _, new = rerun(app_layout, orig)
    key = meta(app_layout, orig)["code"]
    assert _exp(app_layout.app_name, action="prune", version=orig,
                extra_args=["--yes"]) == 0
    assert key in code_objects(app_layout)
    rc, again = rerun(app_layout, new)
    assert rc == 0 and metric_values(app_layout, again) == [1.0]
    assert _exp(app_layout.app_name, action="prune", version=[new, again],
                extra_args=["--yes"]) == 0
    assert key not in code_objects(app_layout)


def test_rerun_of_legacy_in_record_patches_promotes_code_object(app_layout):
    orig = original_run(app_layout)
    storage = _storage(app_layout)
    app = app_layout.app_name
    source, patches = storage.load(app, orig)
    legacy = {k: v for k, v in source.items() if k != "code"}
    storage.save(app, orig, legacy, patches)
    storage.delete(code_app(app), source["code"])

    rc, new = rerun(app_layout, orig)
    assert rc == 0 and metric_values(app_layout, new) == [1.0]
    assert meta(app_layout, new)["code"] == source["code"]
    assert source["code"] in code_objects(app_layout)


def test_rerun_of_clean_run(app_layout):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "value.txt", "7\n")
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN)
    before = run_names(app_layout)
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, "train.py"]) == 0
    (orig,) = run_names(app_layout) - before
    rc, new = rerun(app_layout, orig)
    assert rc == 0 and metric_values(app_layout, new) == [7.0]
    assert "code" not in meta(app_layout, new)


def test_rerun_refuses_code_missing(app_layout):
    orig = original_run(app_layout)
    _storage(app_layout).delete(code_app(app_layout.app_name), meta(app_layout, orig)["code"])
    rc, new = rerun(app_layout, orig)
    assert rc == 1 and new is None


def _output(app_layout, verstr):
    path = _storage(app_layout).artifact_local_path(app_layout.app_name, verstr, "output.log")
    with open(path) as f:
        return f.read()


def test_rerun_uses_recorded_subdir_cwd(app_layout, monkeypatch):
    _bootstrap(app_layout)
    write(app_layout, "src/where.py", "import os\nprint('cwd=' + os.getcwd())\n")
    monkeypatch.setenv("VMN_WORKING_DIR", os.path.join(repo(app_layout), "src"))
    before = run_names(app_layout)
    assert _exp(app_layout.app_name, action="run", run_cmd=[_PY, "where.py"]) == 0
    (orig,) = run_names(app_layout) - before
    assert _state(app_layout, orig)["cwd"] == "src"

    monkeypatch.setenv("VMN_WORKING_DIR", repo(app_layout))
    rc, new = rerun(app_layout, orig)
    assert rc == 0
    assert _state(app_layout, new)["cwd"] == "src"
    cwd = _output(app_layout, new).split("cwd=", 1)[1].splitlines()[0]
    assert os.path.basename(cwd) == "src"
    assert os.path.realpath(cwd) != os.path.realpath(os.path.join(repo(app_layout), "src"))


def test_cwd_flag_overrides(app_layout):
    orig = original_run(app_layout)
    rc, new = rerun(app_layout, orig, extra_args=["--cwd", "sub"],
                    run_cmd=[_PY, "-c", "import os; print(os.getcwd())"])
    # The workspace has no "sub" directory: refused before anything is created.
    assert rc == 1 and new is None
    write(app_layout, "sub/value.txt", "live\n")
    rc, new = rerun(app_layout, orig, extra_args=["--cwd", "."], run_cmd=[_PY, "train.py"])
    assert rc == 0 and _state(app_layout, new)["cwd"] == "."


def test_cwd_outside_workspace_rejected(app_layout, tmp_path):
    orig = original_run(app_layout)
    rc, new = rerun(app_layout, orig, extra_args=[
        "--cwd", "../../..", "--worktree-dir", str(tmp_path / "ws")])
    assert rc == 1 and new is None
    assert not (tmp_path / "ws").exists()


def test_override_after_double_dash_is_recorded_as_command(app_layout):
    orig = original_run(app_layout)
    cmd = [_PY, "-c", "print('override')"]
    rc, new = rerun(app_layout, orig, run_cmd=cmd)
    assert rc == 0
    assert _state(app_layout, new)["command"] == cmd


def test_child_exit_code_propagates_and_status_failed(app_layout):
    orig = original_run(app_layout)
    rc, new = rerun(app_layout, orig, run_cmd=[_PY, "-c", "raise SystemExit(3)"])
    assert rc == 3
    assert derive_status(_state(app_layout, new)) == FAILED


def test_output_log_captured(app_layout):
    orig = original_run(app_layout)
    _, new = rerun(app_layout, orig)
    assert "trained on 1" in _output(app_layout, new)


def test_worktree_removed_by_default(app_layout, tmp_path):
    orig = original_run(app_layout)
    listed = worktrees(app_layout)
    rc, _ = rerun(app_layout, orig, extra_args=["--worktree-dir", str(tmp_path / "ws")])
    assert rc == 0
    assert not (tmp_path / "ws").exists()
    assert worktrees(app_layout) == listed


def test_keep_worktree_prints_and_keeps_path(app_layout, tmp_path, capfd):
    orig = original_run(app_layout)
    ws = tmp_path / "ws"
    capfd.readouterr()
    rc, new = rerun(app_layout, orig, extra_args=["--keep-worktree", "--worktree-dir", str(ws)])
    out = capfd.readouterr()
    assert rc == 0
    assert str(ws) in out.out + out.err
    assert _state(app_layout, new)["workdir"] == str(ws)
    kept = [p for p in ws.rglob("value.txt")]
    assert kept and kept[0].read_text() == "1\n"


def test_setup_failure_creates_no_record(app_layout, tmp_path):
    orig = original_run(app_layout)
    storage = _storage(app_layout)
    source, patches = storage.load(app_layout.app_name, orig)
    patches = dict(patches, working_tree="garbage that is not a patch\n")
    storage.save(code_app(app_layout.app_name), source["code"],
                 {"verstr": source["code"], "has_working_tree_patch": True}, patches)
    rc, new = rerun(app_layout, orig, extra_args=["--worktree-dir", str(tmp_path / "ws")])
    assert rc == 1 and new is None
    assert not (tmp_path / "ws").exists()


def test_nested_create_inside_rerun_lands_in_original_store_with_parent(app_layout):
    orig = original_run(app_layout)
    nested = [_PY, "-m", "vmn_exp.cli", "create", app_layout.app_name]
    before = run_names(app_layout)
    rc = _exp(app_layout.app_name, action="rerun", version=orig, run_cmd=nested)
    assert rc == 0
    new = run_names(app_layout) - before
    assert len(new) == 2, new
    (outer,) = [v for v in new if meta(app_layout, v).get("rerun_of") == orig]
    (inner,) = new - {outer}
    assert meta(app_layout, inner)["parent"] == outer
