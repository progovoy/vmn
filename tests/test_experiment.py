import os
import subprocess
import tarfile

import pytest
import yaml

from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from helpers import (
    DEV_VERSION_RE,
    extract_dev_verstr,
    _experiment,
    _exp,
    _init_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def _make_dirty(app_layout, filename="dirty.txt", content="dirty"):
    app_layout.write_file_commit_and_push("test_repo_0", filename, "initial")
    fpath = os.path.join(app_layout.repo_path, filename)
    with open(fpath, "w") as f:
        f.write(content)
    return fpath


def test_experiment_create_and_list(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout)

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="first experiment")
    assert err == 0
    captured = capfd.readouterr()
    verstr = extract_dev_verstr(captured.out)
    assert verstr is not None
    assert verstr.startswith("0.0.1-dev.")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="list")
    assert err == 0
    captured = capfd.readouterr()
    assert verstr in captured.out
    assert "first experiment" in captured.out
    assert "[1]" in captured.out


def test_experiment_create_auto_init(app_layout, capfd):
    # Auto-init needs a clean working tree (no pending changes) for init+stamp to succeed
    # So we first stamp normally, then create dirty state, then experiment from scratch app
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "auto_init.txt", "auto init content")

    # Experiment create should work on an already-initialized app
    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="auto init test")
    assert err == 0
    captured = capfd.readouterr()
    verstr = extract_dev_verstr(captured.out)
    assert verstr is not None


def test_experiment_create_with_notes_file(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "notes_test.txt")

    notes_path = os.path.join(app_layout.repo_path, "notes.yml")
    with open(notes_path, "w") as f:
        yaml.dump({
            "hypothesis": "lower LR improves convergence",
            "params": {"lr": 0.001, "batch_size": 32},
            "tags": ["baseline", "v1"],
        }, f)

    capfd.readouterr()
    err = _experiment(app_layout.app_name, file=notes_path, note="with notes file")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="show", version=verstr)
    assert err == 0
    captured = capfd.readouterr()
    assert "with notes file" in captured.out


def test_experiment_add_metrics(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "metrics_test.txt")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="metrics test")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    err = _experiment(
        app_layout.app_name, action="add", version=verstr,
        metrics=["loss=0.342", "accuracy=0.91"],
    )
    assert err == 0

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="show", version=verstr)
    assert err == 0
    captured = capfd.readouterr()
    assert "loss" in captured.out
    assert "accuracy" in captured.out


def test_experiment_add_note(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "note_add.txt")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="initial")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    err = _experiment(
        app_layout.app_name, action="add", version=verstr,
        note="overfitting after epoch 12",
    )
    assert err == 0

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="show", version=verstr)
    assert err == 0
    captured = capfd.readouterr()
    assert "overfitting after epoch 12" in captured.out
    assert "Log (2 entries)" in captured.out


def test_experiment_add_artifact(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "artifact_test.txt")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="artifact test")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    artifact_path = os.path.join(app_layout.repo_path, "weights.pt")
    with open(artifact_path, "wb") as f:
        f.write(b"\x00" * 1024)

    err = _experiment(
        app_layout.app_name, action="add", version=verstr,
        attach=artifact_path,
    )
    assert err == 0

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="show", version=verstr)
    assert err == 0
    captured = capfd.readouterr()
    assert "artifact" in captured.out
    assert "weights.pt" in captured.out


def test_experiment_show(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "show_test.txt")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="show me")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="show", latest=True)
    assert err == 0
    captured = capfd.readouterr()
    assert verstr in captured.out
    assert "show me" in captured.out
    assert "Branch:" in captured.out
    assert "Base:" in captured.out


def test_experiment_list_sort_top(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    for i, (fname, loss_val) in enumerate([
        ("sort1.txt", "0.5"), ("sort2.txt", "0.3"), ("sort3.txt", "0.8")
    ]):
        _make_dirty(app_layout, fname, f"content_{i}")
        capfd.readouterr()
        err = _experiment(
            app_layout.app_name, note=f"exp_{i}",
            metrics=[f"loss={loss_val}"],
        )
        assert err == 0

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="list", sort="loss")
    assert err == 0
    captured = capfd.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.strip().startswith("[")]
    assert len(lines) == 3
    assert "loss=0.3" in lines[0]

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="list", sort="loss", top=2)
    assert err == 0
    captured = capfd.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.strip().startswith("[")]
    assert len(lines) == 2


def test_experiment_compare(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    verstrs = []
    for i, fname in enumerate(["cmp1.txt", "cmp2.txt"]):
        _make_dirty(app_layout, fname, f"compare_{i}")
        capfd.readouterr()
        err = _experiment(
            app_layout.app_name, note=f"compare_{i}",
            metrics=[f"loss={0.5 - i * 0.2}"],
        )
        assert err == 0
        v = extract_dev_verstr(capfd.readouterr().out)
        assert v is not None
        verstrs.append(v)

    capfd.readouterr()
    err = _experiment(
        app_layout.app_name, action="compare",
        version=verstrs,
    )
    assert err == 0
    captured = capfd.readouterr()
    assert "loss" in captured.out
    assert "metric" in captured.out


def test_experiment_compare_latest_top_one_errors(app_layout, capfd):
    """--latest --top 1 should error because comparing requires at least 2."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    for i, fname in enumerate(["lat1_a.txt", "lat1_b.txt"]):
        _make_dirty(app_layout, fname, f"latest1_{i}")
        err = _experiment(app_layout.app_name, note=f"exp{i}")
        assert err == 0

    # --latest --top 1 means compare only 1 experiment, which is not enough
    err = _experiment(app_layout.app_name, action="compare", latest=True, top=1)
    assert err != 0


def test_experiment_restore(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    fpath = _make_dirty(app_layout, "restore_exp.txt", "experiment state")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="restore test")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    import subprocess
    subprocess.run(
        ["git", "checkout", "."],
        cwd=app_layout.repo_path, capture_output=True,
    )
    with open(fpath) as f:
        assert f.read() == "initial"

    err = _experiment(app_layout.app_name, action="restore", version=verstr)
    assert err == 0
    with open(fpath) as f:
        assert f.read() == "experiment state"


def test_exp_restore_dirty_tree_auto_saves(app_layout, capfd):
    """Restoring an experiment over dirty work first snapshots that work."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    fpath = _make_dirty(app_layout, "exp_safety.txt", "experiment state A")
    capfd.readouterr()
    _experiment(app_layout.app_name, note="A")
    v_a = extract_dev_verstr(capfd.readouterr().out)

    # Different, unsaved dirty state.
    with open(fpath, "w") as f:
        f.write("experiment state B unsaved")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="restore", version=v_a) == 0
    combined = capfd.readouterr()
    assert "Current work saved as" in (combined.out + combined.err)
    with open(fpath) as f:
        assert f.read() == "experiment state A"


def test_experiment_export_tarball(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "export_exp.txt", "export content")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="export test")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    tar_path = os.path.join(app_layout.repo_path, "experiment_export.tar.gz")
    capfd.readouterr()
    err = _experiment(
        app_layout.app_name, action="export", version=verstr, output=tar_path,
    )
    assert err == 0

    assert os.path.isfile(tar_path)
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
        assert any("vmn_experiment.yml" in n for n in names)
        assert not any(n.endswith("/.git") or n == ".git" for n in names)


def test_experiment_prune(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    for i, fname in enumerate(["prune1.txt", "prune2.txt", "prune3.txt"]):
        _make_dirty(app_layout, fname, f"prune_{i}")
        err = _experiment(app_layout.app_name, note=f"prune_{i}")
        assert err == 0

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="prune", keep=1)
    assert err == 0
    captured = capfd.readouterr()
    assert "Pruned 2" in captured.out
    assert "kept 1" in captured.out

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="list")
    assert err == 0
    captured = capfd.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.strip().startswith("[")]
    assert len(lines) == 1


def test_experiment_prune_keep_zero(app_layout, capfd):
    """--keep 0 should delete all experiments."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    for i, fname in enumerate(["prune_z1.txt", "prune_z2.txt", "prune_z3.txt"]):
        _make_dirty(app_layout, fname, f"prune_zero_{i}")
        err = _experiment(app_layout.app_name, note=f"prune_zero_{i}")
        assert err == 0

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="list")
    assert err == 0
    captured = capfd.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.strip().startswith("[")]
    assert len(lines) == 3

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="prune", keep=0)
    assert err == 0
    captured = capfd.readouterr()
    assert "Pruned 3" in captured.out
    assert "kept 0" in captured.out

    capfd.readouterr()
    err = _experiment(app_layout.app_name, action="list")
    assert err == 0
    captured = capfd.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.strip().startswith("[")]
    assert len(lines) == 0


def test_experiment_create_auto_init_dirty_tree(app_layout, capfd):
    """Experiment create should auto-init repo and app even when the working tree is dirty."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "auto_init_dirty.txt", "dirty content")

    capfd.readouterr()
    err = _experiment("new_dirty_app", note="dirty tree auto init")
    assert err == 0, (
        "experiment create should succeed on uninitialized app with dirty tree"
    )
    captured = capfd.readouterr()
    verstr = extract_dev_verstr(captured.out)
    assert verstr is not None, f"Expected dev verstr in output, got: {captured.out}"


def test_experiment_argparse_latest_before_name():
    """Argparse should not consume app name as --latest value."""
    from version_stamp.cli.args import parse_user_commands
    args = parse_user_commands(["experiment", "--latest", "my_app"])
    assert args.name == "my_app"
    assert args.latest is True

    args = parse_user_commands(["experiment", "show", "my_app", "--latest"])
    assert args.name == "my_app"
    assert args.latest is True
    assert args.action == "show"


def test_experiment_show_latest_before_name(app_layout, capfd):
    """--latest before positional name should not consume the name as its value."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "latest_flag.txt", "latest flag content")

    capfd.readouterr()
    err = _experiment(app_layout.app_name, note="latest flag test")
    assert err == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    reset_logger()
    ret = vmn_run(["experiment", "show", app_layout.app_name, "--latest"])[0]
    assert ret == 0, f"show <name> --latest failed with exit code {ret}"


def test_exp_alias(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "alias_test.txt")

    capfd.readouterr()
    err = _exp(app_layout.app_name, note="alias works")
    assert err == 0
    captured = capfd.readouterr()
    verstr = extract_dev_verstr(captured.out)
    assert verstr is not None

    capfd.readouterr()
    err = _exp(app_layout.app_name, action="list")
    assert err == 0
    captured = capfd.readouterr()
    assert verstr in captured.out
    assert "alias works" in captured.out


# ---------------------------------------------------------------------------
# W3: run-suffix identity (B2), params/metrics split (B6), goal schema (B7),
# clean-tree experiments
# ---------------------------------------------------------------------------


def _exp_log(app_layout, verstr):
    """Load an experiment's log.yml from disk."""
    safe = verstr.replace("+", "_plus_")
    log_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name,
        "experiments", safe, "log.yml",
    )
    with open(log_path) as f:
        return yaml.safe_load(f)


def test_experiment_create_same_state_creates_new_run(app_layout, capfd):
    """B2: creating over identical code state must start a new run (suffix .2),
    never overwrite the earlier experiment's log."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _make_dirty(app_layout, "run_state.txt", "same content")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="run one") == 0
    v1 = extract_dev_verstr(capfd.readouterr().out)
    assert v1 is not None

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="run two") == 0
    v2 = extract_dev_verstr(capfd.readouterr().out)
    assert v2 is not None

    assert v2 == f"{v1}.r2"

    # Both runs are listed.
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    list_out = capfd.readouterr().out
    assert v1 in list_out
    assert v2 in list_out

    # The first run's log survived intact.
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=v1) == 0
    assert "run one" in capfd.readouterr().out

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=v2) == 0
    assert "run two" in capfd.readouterr().out


def test_experiment_run_suffix_addressable(app_layout, capfd):
    """B2: a run-suffixed id addresses exactly that run for add/show."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    _make_dirty(app_layout, "addr_state.txt", "content")

    capfd.readouterr()
    _experiment(app_layout.app_name, note="one")
    v1 = extract_dev_verstr(capfd.readouterr().out)
    capfd.readouterr()
    _experiment(app_layout.app_name, note="two")
    v2 = extract_dev_verstr(capfd.readouterr().out)
    assert v2 == f"{v1}.r2"

    # Add a metric only to run 2.
    assert _experiment(
        app_layout.app_name, action="add", version=v2, metrics=["acc=0.9"]
    ) == 0

    capfd.readouterr()
    _experiment(app_layout.app_name, action="show", version=v2)
    assert "acc" in capfd.readouterr().out

    capfd.readouterr()
    _experiment(app_layout.app_name, action="show", version=v1)
    assert "acc" not in capfd.readouterr().out


def test_goto_experiment_run_id(app_layout, capfd):
    """B2: `vmn goto` restores a run-suffixed experiment id from experiments/."""
    from helpers import _goto

    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    tracked = _make_dirty(app_layout, "goto_run.txt", "dirty A")

    capfd.readouterr()
    _experiment(app_layout.app_name, note="one")
    v1 = extract_dev_verstr(capfd.readouterr().out)
    capfd.readouterr()
    _experiment(app_layout.app_name, note="two")
    v2 = extract_dev_verstr(capfd.readouterr().out)
    assert v2 == f"{v1}.r2"

    # Revert the working tree.
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, capture_output=True)
    with open(tracked) as f:
        assert f.read() == "initial"

    # goto the run-suffixed id restores the captured dirty content.
    assert _goto(app_layout.app_name, version=v2) == 0
    with open(tracked) as f:
        assert f.read() == "dirty A"


def test_dev_version_parsing_run_suffix():
    """B2: deserialize_vmn_version parses the optional run suffix."""
    from version_stamp.core.version_math import deserialize_vmn_version

    props = deserialize_vmn_version("1.2.3-dev.abc1234.def5678.r2")
    assert "dev" in props.types
    assert props.dev_commit == "abc1234"
    assert props.dev_diff_hash == "def5678"
    assert props.dev_run == 2

    # Without a suffix, dev_run is None.
    props0 = deserialize_vmn_version("1.2.3-dev.abc1234.def5678")
    assert props0.dev_run is None


def test_experiment_create_metrics_and_file_params_coexist(app_layout, capfd, tmp_path):
    """B6: --metrics on create must not clobber -f params; they become a
    separate metrics entry."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    _make_dirty(app_layout, "coexist.txt", "content")

    params_file = tmp_path / "params.yml"
    params_file.write_text("params:\n  lr: 0.01\n  batch_size: 32\nhypothesis: baseline\n")

    capfd.readouterr()
    assert _experiment(
        app_layout.app_name, note="both",
        metrics=["loss=0.5"], file=str(params_file),
    ) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    log = _exp_log(app_layout, verstr)
    create_entry = next(e for e in log if e.get("type") == "create")
    assert create_entry["params"]["lr"] == 0.01
    assert create_entry["params"]["batch_size"] == 32
    assert create_entry.get("hypothesis") == "baseline"

    metrics_entries = [e for e in log if e.get("type") == "metrics"]
    assert len(metrics_entries) == 1
    assert metrics_entries[0]["values"]["loss"] == 0.5


def _setup_three_experiments(app_layout, capfd, experiment_conf):
    """Init an app with a metrics schema and create 3 experiments with metrics."""
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    app_layout.write_conf(
        params["app_conf_path"],
        template="[{major}][.{minor}][.{patch}]",
        experiment=experiment_conf,
    )
    _stamp_app(app_layout.app_name, "patch")

    verstrs = []
    for i, (loss, acc) in enumerate([(0.5, 0.80), (0.3, 0.91), (0.4, 0.85)]):
        # Distinct code state per experiment so each gets its own verstr.
        _make_dirty(app_layout, f"schema_{i}.txt", f"content {i}")
        capfd.readouterr()
        _experiment(
            app_layout.app_name, note=f"run{i}",
            metrics=[f"loss={loss}", f"acc={acc}"],
        )
        verstrs.append(extract_dev_verstr(capfd.readouterr().out))
    return verstrs


def test_experiment_metrics_schema_goal_max_sorts_descending(app_layout, capfd):
    """B7: goal: max sorts best (highest) first."""
    _setup_three_experiments(
        app_layout, capfd, {"metrics": {"acc": {"goal": "max"}}}
    )

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list", sort="acc") == 0
    lines = [l for l in capfd.readouterr().out.strip().split("\n") if l.startswith("[")]
    assert "acc=0.91" in lines[0]
    assert "acc=0.8" in lines[-1]


def test_experiment_metrics_schema_goal_min_sorts_ascending(app_layout, capfd):
    """B7: goal: min sorts best (lowest) first."""
    _setup_three_experiments(
        app_layout, capfd, {"metrics": {"loss": {"goal": "min"}}}
    )

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list", sort="loss") == 0
    lines = [l for l in capfd.readouterr().out.strip().split("\n") if l.startswith("[")]
    assert "loss=0.3" in lines[0]
    assert "loss=0.5" in lines[-1]


def test_experiment_metrics_schema_primary_default_sort(app_layout, capfd):
    """B7: with no --sort, the primary metric drives the leaderboard order."""
    _setup_three_experiments(
        app_layout, capfd,
        {"metrics": {"loss": {"goal": "min", "primary": True}}},
    )

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    lines = [l for l in capfd.readouterr().out.strip().split("\n") if l.startswith("[")]
    assert "loss=0.3" in lines[0]


def test_experiment_metrics_schema_legacy_sort_desc_warns(app_layout, capfd):
    """B7: legacy `sort: desc` still works but warns about deprecation."""
    _setup_three_experiments(
        app_layout, capfd, {"metrics": {"acc": {"sort": "desc"}}}
    )

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list", sort="acc") == 0
    captured = capfd.readouterr()
    lines = [l for l in captured.out.strip().split("\n") if l.startswith("[")]
    assert "acc=0.91" in lines[0]
    assert "deprecated" in captured.err.lower()


def test_experiment_create_without_git_remote(app_layout, capfd):
    """B3: experiments are local-first — no git remote required."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "local_only.txt", "initial")
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=app_layout.repo_path, capture_output=True,
    )
    with open(os.path.join(app_layout.repo_path, "local_only.txt"), "w") as f:
        f.write("dirty without a remote")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="local only") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    assert verstr in capfd.readouterr().out


def test_exp_create_clean_tree_zero_hash(app_layout, capfd):
    """Clean-tree experiment creates a real record with a zeroed diff hash."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Tree is clean right after stamp.
    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="clean run") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    assert verstr.endswith(".0000000")

    # It is a real, listable experiment.
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    assert verstr in capfd.readouterr().out


# ---------------------------------------------------------------------------
# W5: implicit latest / --last N / @N addressing / candidate listing
# ---------------------------------------------------------------------------


def _make_n_experiments(app_layout, capfd, n):
    verstrs = []
    for i in range(n):
        _make_dirty(app_layout, f"exp_{i}.txt", f"content {i}")
        capfd.readouterr()
        _experiment(app_layout.app_name, note=f"run{i}", metrics=[f"loss=0.{i}"])
        verstrs.append(extract_dev_verstr(capfd.readouterr().out))
    return verstrs


def test_exp_list_last_n(app_layout, capfd):
    """--last N limits the leaderboard to the N most recent experiments."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    verstrs = _make_n_experiments(app_layout, capfd, 3)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list", last=2) == 0
    lines = [l for l in capfd.readouterr().out.strip().split("\n") if l.startswith("[")]
    assert len(lines) == 2
    # The oldest experiment is excluded.
    assert verstrs[0] not in "\n".join(lines)


def test_exp_compare_no_args_uses_latest_two(app_layout, capfd):
    """compare with no -v/--last compares the latest two experiments."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    verstrs = _make_n_experiments(app_layout, capfd, 3)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="compare") == 0
    out = capfd.readouterr().out
    # Latest two present, oldest absent from the comparison columns.
    assert "loss" in out
    assert verstrs[0][-12:] not in out


def test_exp_ambiguous_prefix_lists_candidates(app_layout, capfd):
    """An ambiguous experiment prefix reports the matching candidates."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    verstrs = _make_n_experiments(app_layout, capfd, 2)

    capfd.readouterr()
    ret = _experiment(app_layout.app_name, action="show", version="0.0.1-dev.")
    assert ret == 1
    err = capfd.readouterr().err
    assert "mbiguous" in err
    for v in verstrs:
        assert v in err


def test_exp_show_at_index(app_layout, capfd):
    """@N addresses the N-th experiment shown by list."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    verstrs = _make_n_experiments(app_layout, capfd, 2)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version="@1") == 0
    assert verstrs[0] in capfd.readouterr().out


# ---------------------------------------------------------------------------
# W7: vmn exp run — one-command experiment execution
# ---------------------------------------------------------------------------

import sys as _sys

_PY = _sys.executable or "python3"


def test_exp_run_records_command_exit_code_and_duration(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="run", note="a run",
        run_cmd=[_PY, "-c", "print('hello from run')"],
    )
    assert ret == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    log = _exp_log(app_layout, verstr)
    run_entries = [e for e in log if e.get("type") == "run"]
    assert len(run_entries) == 1
    entry = run_entries[0]
    assert entry["exit_code"] == 0
    assert entry["command"][-1] == "print('hello from run')"
    assert isinstance(entry["duration_sec"], (int, float))


def test_exp_run_captures_metrics_file(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    script = (
        "import os\n"
        "with open(os.environ['VMN_METRICS_FILE'], 'a') as f:\n"
        "    f.write('loss=0.11\\nacc=0.97\\n')\n"
    )
    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="run",
        run_cmd=[_PY, "-c", script],
    )
    assert ret == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    assert "loss" in out
    assert "acc" in out


def test_exp_run_propagates_child_exit_code(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="run",
        run_cmd=[_PY, "-c", "import sys; sys.exit(3)"],
    )
    assert ret == 3


def test_exp_run_sets_experiment_env(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    script = (
        "import os\n"
        "with open('env_dump.txt', 'w') as f:\n"
        "    f.write(os.environ.get('VMN_EXPERIMENT_ID','') + '\\n')\n"
        "    f.write(os.environ.get('VMN_APP_NAME','') + '\\n')\n"
    )
    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="run",
        run_cmd=[_PY, "-c", script],
    )
    assert ret == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    with open(os.path.join(app_layout.repo_path, "env_dump.txt")) as f:
        lines = f.read().strip().split("\n")
    assert lines[0] == verstr
    assert lines[1] == app_layout.app_name


def test_exp_run_clean_tree_creates_experiment(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    # Clean tree right after stamp.
    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="run",
        run_cmd=[_PY, "-c", "print('clean run')"],
    )
    assert ret == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    assert verstr.endswith(".0000000")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    assert verstr in capfd.readouterr().out


def test_exp_run_requires_double_dash(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    capfd.readouterr()
    # No command after --
    ret = _experiment(app_layout.app_name, action="run")
    assert ret == 1


def test_exp_run_cold_start_fresh_repo(app_layout, capfd):
    """Zero setup: exp run on a fresh repo auto-inits, stamps, and records."""
    capfd.readouterr()
    ret = _experiment(
        "cold_model", action="run",
        run_cmd=[_PY, "-c", "print('cold start')"],
    )
    assert ret == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    capfd.readouterr()
    assert _experiment("cold_model", action="list") == 0
    assert verstr in capfd.readouterr().out


# ---------------------------------------------------------------------------
# W9: first-class exp diff (real tree diff + delta header)
# ---------------------------------------------------------------------------


def _two_experiments_shared_base(app_layout, capfd):
    """Two experiments over the same base commit, differing in shared.txt +
    metrics. Returns (v_alpha, v_beta)."""
    app_layout.write_file_commit_and_push("test_repo_0", "shared.txt", "base line")
    p = os.path.join(app_layout.repo_path, "shared.txt")

    with open(p, "w") as f:
        f.write("ALPHA_MARKER_LINE\n")
    capfd.readouterr()
    _experiment(app_layout.app_name, note="alpha", metrics=["loss=0.5"])
    v_alpha = extract_dev_verstr(capfd.readouterr().out)

    with open(p, "w") as f:
        f.write("BETA_MARKER_LINE\n")
    capfd.readouterr()
    _experiment(app_layout.app_name, note="beta", metrics=["loss=0.3"])
    v_beta = extract_dev_verstr(capfd.readouterr().out)
    return v_alpha, v_beta


def test_exp_diff_real_tree_diff_output(app_layout, capfd):
    """exp diff shows the actual changed source lines, not patch-file syntax."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    v_alpha, v_beta = _two_experiments_shared_base(app_layout, capfd)

    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="diff", version=[v_alpha, v_beta],
    )
    assert ret == 0
    out = capfd.readouterr().out
    assert "ALPHA_MARKER_LINE" in out
    assert "BETA_MARKER_LINE" in out
    # Not a diff of the internal .patch files.
    assert "working_tree.patch" not in out


def test_exp_diff_defaults_to_latest_two(app_layout, capfd):
    """exp diff with no -v diffs the two most recent experiments."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    v_alpha, v_beta = _two_experiments_shared_base(app_layout, capfd)

    capfd.readouterr()
    ret = _experiment(app_layout.app_name, action="diff")
    assert ret == 0
    out = capfd.readouterr().out
    assert "ALPHA_MARKER_LINE" in out
    assert "BETA_MARKER_LINE" in out


def test_exp_diff_delta_header_params_metrics(app_layout, capfd):
    """exp diff prints a metrics delta header before the code diff."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    v_alpha, v_beta = _two_experiments_shared_base(app_layout, capfd)

    capfd.readouterr()
    ret = _experiment(
        app_layout.app_name, action="diff", version=[v_alpha, v_beta],
    )
    assert ret == 0
    out = capfd.readouterr().out
    assert "metrics" in out
    assert "loss" in out
    assert "0.5" in out
    assert "0.3" in out
