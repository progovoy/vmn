"""``vmn-exp rerun``: refusals, warnings, ``--dry-run``, ``--print`` and how
``show``/``list`` present a rerun."""
import json
import subprocess

import pytest
import yaml
from helpers import _PY, _bootstrap, _exec_script, _exp, _storage
from rerun_helpers import (
    code_objects, meta, original_run, rerun, run_names, worktrees,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _out(capfd):
    captured = capfd.readouterr()
    return captured.out + captured.err


def test_rerun_is_an_experiment_action():
    from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS

    assert "rerun" in EXPERIMENT_ACTIONS


def test_ref_required(app_layout, capfd):
    original_run(app_layout)
    capfd.readouterr()
    rc, new = rerun(app_layout)
    assert rc == 1 and new is None
    assert "-v" in _out(capfd)


def test_created_only_run_errors_no_command(app_layout, capfd):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name) == 0
    (orig,) = run_names(app_layout)
    capfd.readouterr()
    rc, new = rerun(app_layout, orig)
    assert rc == 1 and new is None
    assert "after `--`" in _out(capfd)


def test_sdk_run_errors_with_hint_and_override_yields_inner_run(app_layout, capfd):
    _bootstrap(app_layout)
    body = (
        "from vmn_exp.sdk import start_run\n"
        f"with start_run({app_layout.app_name!r}) as run:\n"
        "    run.log_metric('m', 5)\n"
    )
    _exec_script(app_layout, "sdk_train.py", body)
    subprocess.run([_PY, "sdk_train.py"], cwd=app_layout.repo_path, check=True)
    (orig,) = run_names(app_layout)
    capfd.readouterr()
    rc, new = rerun(app_layout, orig)
    assert rc == 1 and new is None
    assert "-- python sdk_train.py" in _out(capfd)

    before = run_names(app_layout)
    assert _exp(app_layout.app_name, action="rerun", version=orig,
                run_cmd=[_PY, "sdk_train.py"]) == 0
    new = run_names(app_layout) - before
    assert len(new) == 2
    (outer,) = [v for v in new if meta(app_layout, v).get("rerun_of") == orig]
    (inner,) = new - {outer}
    assert meta(app_layout, inner)["parent"] == outer


def test_imported_run_refused_no_code(app_layout, capfd):
    orig = original_run(app_layout)
    storage = _storage(app_layout)
    source, patches = storage.load(app_layout.app_name, orig)
    storage.save(app_layout.app_name, orig,
                 dict({k: v for k, v in source.items() if k != "base_commit"},
                      imported_from={"tool": "mlflow"}), patches)
    capfd.readouterr()
    rc, new = rerun(app_layout, orig)
    assert rc == 1 and new is None
    assert "Cannot rerun" in _out(capfd)


def test_dry_run_creates_nothing_and_prints_plan(app_layout, tmp_path, capfd):
    orig = original_run(app_layout)
    runs, codes, trees = run_names(app_layout), code_objects(app_layout), worktrees(app_layout)
    capfd.readouterr()
    rc, new = rerun(app_layout, orig, extra_args=["--dry-run", "--worktree-dir",
                                                  str(tmp_path / "ws")])
    out = _out(capfd)
    assert rc == 0 and new is None
    assert run_names(app_layout) == runs and code_objects(app_layout) == codes
    assert worktrees(app_layout) == trees and not (tmp_path / "ws").exists()
    assert orig in out and "train.py" in out
    assert meta(app_layout, orig)["code"] in out
    assert meta(app_layout, orig)["base_commit"][:7] in out


def test_print_shows_command_cwd_code_and_recipe(app_layout, capfd):
    orig = original_run(app_layout)
    runs, trees = run_names(app_layout), worktrees(app_layout)
    capfd.readouterr()
    rc, new = rerun(app_layout, orig, extra_args=["--print"])
    out = _out(capfd)
    assert rc == 0 and new is None
    assert run_names(app_layout) == runs and worktrees(app_layout) == trees
    source = meta(app_layout, orig)
    assert "train.py" in out
    assert source["code_verstr"] in out and source["code"] in out
    assert f"vmn-exp rerun {app_layout.app_name} -v {orig}" in out


def test_print_json(app_layout, capfd):
    orig = original_run(app_layout)
    capfd.readouterr()
    rc, _ = rerun(app_layout, orig, extra_args=["--print", "--json"])
    assert rc == 0
    printed = json.loads(capfd.readouterr().out.strip().splitlines()[-1])
    source = meta(app_layout, orig)
    assert printed["rerun_of"] == orig
    assert printed["command"] == [_PY, "train.py"]
    assert printed["cwd"] == "."
    assert printed["code_verstr"] == source["code_verstr"]
    assert printed["code"] == source["code"]
    assert printed["recipe"] == f"vmn-exp rerun {app_layout.app_name} -v {orig}"
    assert "vmn-exp export" in printed["export_recipe"]


def test_env_diff_warning_printed(app_layout, capfd):
    orig = original_run(app_layout)
    storage = _storage(app_layout)
    env = yaml.safe_load(storage.load_file(app_layout.app_name, orig, "env.yml"))
    env["python"] = "2.7.0"
    storage.save_file(app_layout.app_name, orig, "env.yml", yaml.dump(env))
    capfd.readouterr()
    rc, _ = rerun(app_layout, orig)
    assert rc == 0
    assert "2.7.0" in _out(capfd)


def test_no_env_skips_capture_and_diff(app_layout, capfd):
    orig = original_run(app_layout)
    storage = _storage(app_layout)
    env = yaml.safe_load(storage.load_file(app_layout.app_name, orig, "env.yml"))
    env["python"] = "2.7.0"
    storage.save_file(app_layout.app_name, orig, "env.yml", yaml.dump(env))
    capfd.readouterr()
    rc, new = rerun(app_layout, orig, extra_args=["--no-env"])
    assert rc == 0
    assert "2.7.0" not in _out(capfd)
    assert "env" not in meta(app_layout, new)


def test_untracked_skipped_warning(app_layout, capfd):
    orig = original_run(app_layout)
    storage = _storage(app_layout)
    source, patches = storage.load(app_layout.app_name, orig)
    storage.save(app_layout.app_name, orig,
                 dict(source, untracked_skipped=["big.bin"]), {})
    capfd.readouterr()
    rc, _ = rerun(app_layout, orig)
    assert rc == 0
    assert "big.bin" in _out(capfd)


def test_sweep_trial_rerun_sees_sweep_params_and_is_not_a_trial(app_layout, tmp_path):
    trial = tmp_path / "trial.yml"
    trial.write_text(yaml.dump({"params": {"lr": 0.1},
                                "tags": {"sweep": "s", "sweep_trial": "0"}}))
    orig = original_run(app_layout, extra_args=["-f", str(trial)])
    storage = _storage(app_layout)
    probe = ("import json, os; open(os.environ['VMN_METRICS_FILE'], 'a').write("
             "'lr=%s trial=%d\\n' % (json.loads(os.environ['VMN_SWEEP_PARAMS'])['lr'], "
             "'VMN_SWEEP_TRIAL' in os.environ))")
    rc, new = rerun(app_layout, orig, run_cmd=[_PY, "-c", probe])
    assert rc == 0
    values = [e["values"] for e in storage.load_merged_log(app_layout.app_name, new)
              if e.get("type") == "metrics"]
    assert values == [{"lr": 0.1, "trial": 0.0}]


def test_rerun_refused_in_from_snapshot_mode(app_layout, tmp_path, monkeypatch, capfd):
    orig = original_run(app_layout)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(tmp_path / "vmn_metadata.yml"))
    capfd.readouterr()
    rc, new = rerun(app_layout, orig)
    assert rc == 1 and new is None
    assert "requires a git repository" in _out(capfd)


def test_show_prints_rerun_of(app_layout, capfd):
    orig = original_run(app_layout)
    _, new = rerun(app_layout, orig)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="show", version=new) == 0
    assert f"Rerun of: {orig}" in _out(capfd)


def test_list_query_rerun_of(app_layout, capfd):
    orig = original_run(app_layout)
    _, new = rerun(app_layout, orig)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list",
                extra_args=["--query", f'rerun_of = "{orig}"', "--json"]) == 0
    rows = json.loads(capfd.readouterr().out)
    assert [r["verstr"] for r in rows] == [new]


def test_fork_from_is_rejected(app_layout, capfd):
    orig = original_run(app_layout)
    capfd.readouterr()
    rc, new = rerun(app_layout, orig, extra_args=["--fork-from", orig])
    assert rc == 1 and new is None
    assert "--fork-from" in _out(capfd)


def test_source_still_running_warns(app_layout, capfd):
    from vmn_exp.core.status import load_run_state
    from vmn_exp.core.writer import save_run_state
    from version_stamp.api import now_iso

    orig = original_run(app_layout)
    storage = _storage(app_layout)
    state = load_run_state(storage, app_layout.app_name, orig)
    save_run_state(storage, app_layout.app_name, orig, state, state="running",
                   exit_code=None, heartbeat=now_iso())
    capfd.readouterr()
    rc, _ = rerun(app_layout, orig)
    assert rc == 0
    assert "still running" in _out(capfd)
