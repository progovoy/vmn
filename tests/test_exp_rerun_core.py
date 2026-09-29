"""Pure helpers behind ``vmn-exp rerun`` (``vmn_exp.core.rerun``)."""
import json
import os

from vmn_exp.core import rerun
from vmn_exp.core.code_store import CODE_MISSING
from vmn_exp.core.rerun import Invocation, RUNNER_CLI, RUNNER_SDK

CODE_FIELDS = {
    "base_version": "0.0.1",
    "base_commit": "abc123",
    "branch": "main",
    "remote": "git@example.com:r.git",
    "app_name": "app",
    "dirty_states": ["pending"],
    "has_working_tree_patch": True,
    "has_local_commits_patch": False,
    "has_untracked_files": True,
    "has_dep_patches": False,
    "diff_hash": "f" * 64,
    "untracked_skipped": ["big.bin"],
    "changesets": {".": {"hash": "abc123"}},
    "code": "0.0.1-dev.abc123.fffffff." + "f" * 64,
}
RUN_IDENTITY = {
    "verstr": "0.0.1-dev.abc123.fffffff.r2",
    "code_verstr": "0.0.1-dev.abc123.fffffff",
    "parent": "p",
    "name": "baseline",
    "archived": True,
    "tags": {"a": "b"},
    "forked_from": {"verstr": "x", "step": 1},
    "rerun_of": "older",
    "from_snapshot": True,
    "imported_from": {"tool": "mlflow"},
    CODE_MISSING: True,
    "timestamp": "2026-01-01T00:00:00Z",
    "note": "old note",
    "env": {"python": "3.11"},
}
META = dict(CODE_FIELDS, **RUN_IDENTITY)


def _template():
    return rerun.rerun_template(META, "orig", "again", "2026-09-29T00:00:00Z")


def test_template_keeps_code_identity_fields_and_code_key():
    template = _template()
    for key, value in CODE_FIELDS.items():
        assert template[key] == value


def test_template_drops_run_identity():
    template = _template()
    for key in ("verstr", "code_verstr", "parent", "name", "archived", "tags",
                "forked_from", "from_snapshot", "imported_from", CODE_MISSING, "env"):
        assert key not in template


def test_template_records_rerun_of():
    template = _template()
    assert template["rerun_of"] == "orig"
    assert template["note"] == "again"
    assert template["timestamp"] == "2026-09-29T00:00:00Z"


def test_template_omits_absent_code_fields():
    template = rerun.rerun_template({"verstr": "v", "base_commit": "c"}, "v", None, "t")
    assert "code" not in template and "diff_hash" not in template
    assert template["base_commit"] == "c"


def test_code_verstr_of_prefers_recorded_then_verstr():
    assert rerun.code_verstr_of({"verstr": "v.r2", "code_verstr": "v"}) == "v"
    assert rerun.code_verstr_of({"verstr": "v"}) == "v"


def test_blocker_no_base_commit_names_import_source():
    meta = {"imported_from": {"tool": "mlflow", "run_id": "r1"}}
    assert "mlflow" in rerun.rerun_blocker(meta)


def test_blocker_code_missing_refused():
    meta = {"base_commit": "c", "code": "k", CODE_MISSING: True}
    assert "missing" in rerun.rerun_blocker(meta)


def test_blocker_none_for_normal_run():
    assert rerun.rerun_blocker({"base_commit": "c"}) is None


def test_blocker_from_snapshot_dirty_without_code_refused():
    meta = {"base_commit": "c", "from_snapshot": True, "dirty_states": ["pending"]}
    assert rerun.rerun_blocker(meta)
    assert rerun.rerun_blocker(meta, code_key="v.hash") is None


def test_blocker_from_snapshot_clean_allowed():
    meta = {"base_commit": "c", "from_snapshot": True, "dirty_states": []}
    assert rerun.rerun_blocker(meta) is None


def test_invocation_from_run_state():
    state = {"command": ["python", "t.py"], "cwd": "src", "runner": RUNNER_CLI}
    assert rerun.recorded_invocation(state, []) == Invocation(
        ["python", "t.py"], "src", RUNNER_CLI
    )


def test_invocation_falls_back_to_last_run_log_entry():
    log = [
        {"type": "create"},
        {"type": "run", "command": ["a"]},
        {"type": "metrics"},
        {"type": "run", "command": ["b", "1"]},
    ]
    assert rerun.recorded_invocation(None, log) == Invocation(["b", "1"], None, RUNNER_CLI)


def test_invocation_none_for_created_only():
    assert rerun.recorded_invocation(None, [{"type": "create"}]) is None
    assert rerun.recorded_invocation({}, []) is None


def test_legacy_state_without_runner_is_exp_run():
    inv = rerun.recorded_invocation({"command": ["x"]}, [])
    assert inv.runner == RUNNER_CLI and inv.cwd is None


def test_resolve_recorded_cli_command():
    inv = Invocation(["python", "t.py"], "src", RUNNER_CLI)
    assert rerun.resolve_command(inv, None) == (inv, None)


def test_sdk_invocation_refused_without_override_and_hint_prefixes_python():
    inv = Invocation(["train.py", "--lr", "0.1"], ".", RUNNER_SDK)
    resolved, err = rerun.resolve_command(inv, None)
    assert resolved is None
    assert "-- python train.py --lr 0.1" in err


def test_no_command_is_error():
    resolved, err = rerun.resolve_command(None, None)
    assert resolved is None and "--" in err


def test_override_replaces_command_keeps_recorded_cwd():
    inv = Invocation(["train.py"], "src", RUNNER_SDK)
    resolved, err = rerun.resolve_command(inv, ["python", "train.py"])
    assert err is None
    assert resolved == Invocation(["python", "train.py"], "src", RUNNER_CLI)
    assert rerun.resolve_command(None, ["x"]) == (Invocation(["x"], None, RUNNER_CLI), None)


def test_empty_override_is_error():
    inv = Invocation(["x"], ".", RUNNER_CLI)
    resolved, err = rerun.resolve_command(inv, [])
    assert resolved is None and err


def test_create_params_from_create_entry():
    log = [
        {"type": "create", "note": "n", "params": {"lr": 0.1}},
        {"type": "params", "params": {"x": 1}},
    ]
    assert rerun.create_params(log) == {"lr": 0.1}
    assert rerun.create_params([{"type": "create"}]) == {}
    assert rerun.create_params([]) == {}


def test_repo_relative_cwd_inside_root_outside(tmp_path):
    root = tmp_path / "repo"
    sub = root / "src" / "pkg"
    sub.mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert rerun.repo_relative_cwd(str(root), str(root)) == "."
    assert rerun.repo_relative_cwd(str(sub), str(root)) == "src/pkg"
    assert rerun.repo_relative_cwd(str(other), str(root)) is None
    assert rerun.repo_relative_cwd(str(sub), None) is None


def test_repo_relative_cwd_resolves_symlinks(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(root)
    assert rerun.repo_relative_cwd(str(link / "src"), str(root)) == "src"


def test_remap_live_paths_moves_absolute_repo_paths_only():
    live = os.path.join(os.sep, "live", "repo")
    work = os.path.join(os.sep, "tmp", "w", "repo")
    argv = [
        "python",
        os.path.join(live, "train.py"),
        "--data=" + os.path.join(live, "data"),
        "rel/path",
        os.path.join(os.sep, "live", "repository", "x"),
        os.path.join(os.sep, "etc", "hosts"),
        live,
    ]
    assert rerun.remap_live_paths(argv, live, work) == [
        "python",
        os.path.join(work, "train.py"),
        "--data=" + os.path.join(work, "data"),
        "rel/path",
        os.path.join(os.sep, "live", "repository", "x"),
        os.path.join(os.sep, "etc", "hosts"),
        work,
    ]


def test_child_env_sets_working_dir_experiment_dir_and_drops_resume_id():
    env = rerun.child_env("/w/repo/src", "/live/repo")
    assert env["VMN_WORKING_DIR"] == "/w/repo/src"
    assert env["VMN_EXPERIMENT_DIR"] == "/live/repo"
    # None in extra_env removes the variable from the child's env.
    assert env["VMN_RESUME_RUN_ID"] is None
    assert "VMN_SWEEP_PARAMS" not in env


def test_child_env_without_experiment_dir_leaves_it_alone():
    assert "VMN_EXPERIMENT_DIR" not in rerun.child_env("/w", None)


def test_child_env_reexports_sweep_params():
    env = rerun.child_env("/w", "/r", sweep_params={"lr": 0.1})
    assert json.loads(env["VMN_SWEEP_PARAMS"]) == {"lr": 0.1}
    assert "VMN_SWEEP_ID" not in env and "VMN_SWEEP_TRIAL" not in env

