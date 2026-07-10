import os
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
