"""`vmn-exp export`: materializing a recorded dev version into a plain tree
(local-first, no untracked leakage) that a git-less container records against."""
import os
import subprocess

import pytest
import yaml

from vmn_exp.snapshot import LocalSnapshotStorage
from version_stamp.core import logging as vmn_logging
from version_stamp.core.git_cmd import clone_at_commit
from exp_helpers import _PY, _SRC_PATH, _bootstrap, _experiment, extract_dev_verstr
from vmn_exp.storage.areas import local_store_root

UNREACHABLE_REMOTE = "https://127.0.0.1:9/no/such/repo.git"


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _recorded_dirty_state(app_layout, capfd, note=None):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial")
    with open(os.path.join(app_layout.repo_path, "tracked.txt"), "w") as f:
        f.write("dirty tracked")
    capfd.readouterr()
    assert _experiment(app_layout.app_name, note=note) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _export(app_layout, verstr, out):
    return _experiment(app_layout.app_name, action="export", version=verstr, output=out)


def _rewrite_meta(app_layout, verstr, **updates):
    storage = LocalSnapshotStorage(local_store_root(app_layout.repo_path), area="runs")
    path = os.path.join(storage._snapshot_dir(app_layout.app_name, verstr), "metadata.yml")
    with open(path) as f:
        meta = yaml.safe_load(f)
    meta.update(updates)
    with open(path, "w") as f:
        yaml.dump(meta, f)


def test_export_to_a_directory_materializes_the_code(app_layout, capfd, tmp_path):
    verstr = _recorded_dirty_state(app_layout, capfd)
    out = str(tmp_path / "export")

    assert _export(app_layout, verstr, out) == 0

    with open(os.path.join(out, "tracked.txt")) as f:
        assert f.read() == "dirty tracked"
    with open(os.path.join(out, "vmn_metadata.yml")) as f:
        assert yaml.safe_load(f)["verstr"] == verstr
    assert not os.path.isdir(os.path.join(out, ".git"))


def test_export_without_a_git_remote_clones_the_local_repo(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "noremote.txt", "initial")
    subprocess.run(
        ["git", "remote", "remove", "origin"], cwd=app_layout.repo_path, capture_output=True
    )
    with open(os.path.join(app_layout.repo_path, "noremote.txt"), "w") as f:
        f.write("modified with no remote")
    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    out = str(tmp_path / "export")

    assert _export(app_layout, verstr, out) == 0
    with open(os.path.join(out, "noremote.txt")) as f:
        assert f.read() == "modified with no remote"


def test_export_uses_local_commit_when_remote_is_unreachable(app_layout, capfd, tmp_path):
    verstr = _recorded_dirty_state(app_layout, capfd)
    _rewrite_meta(app_layout, verstr, remote=UNREACHABLE_REMOTE)
    out = str(tmp_path / "export")

    assert _export(app_layout, verstr, out) == 0
    with open(os.path.join(out, "tracked.txt")) as f:
        assert f.read() == "dirty tracked"


def test_local_materialize_never_touches_the_network(app_layout, capfd, tmp_path, monkeypatch):
    verstr = _recorded_dirty_state(app_layout, capfd)
    _rewrite_meta(app_layout, verstr, remote=UNREACHABLE_REMOTE)
    real_run = subprocess.run
    network = []

    def spy(cmd, *args, **kwargs):
        if isinstance(cmd, list) and UNREACHABLE_REMOTE in cmd:
            network.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    assert _export(app_layout, verstr, str(tmp_path / "export")) == 0
    assert network == []


def test_export_does_not_copy_live_untracked_files(app_layout, capfd, tmp_path):
    verstr = _recorded_dirty_state(app_layout, capfd)
    # Created after the record: not part of it, must not leak into the export.
    with open(os.path.join(app_layout.repo_path, "leak.txt"), "w") as f:
        f.write("not in the record")
    out = str(tmp_path / "export")

    assert _export(app_layout, verstr, out) == 0
    assert not os.path.exists(os.path.join(out, "leak.txt"))


def test_clone_timeout_is_an_error_not_a_hang(tmp_path, monkeypatch):
    def timeout(cmd, *args, **kwargs):
        assert kwargs.get("timeout"), f"no timeout on {cmd}"
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)

    assert clone_at_commit(str(tmp_path / "d"), UNREACHABLE_REMOTE, "a" * 40) == 1


def _vmn_exp_without_git(cwd, *argv):
    env = {**os.environ, "PYTHONPATH": _SRC_PATH, "GIT_CEILING_DIRECTORIES": str(cwd)}
    for key in ("VMN_WORKING_DIR", "VMN_EXPERIMENT_ID", "VMN_SNAPSHOT_METADATA"):
        env.pop(key, None)
    return subprocess.run(
        [_PY, "-m", "vmn_exp.cli", *argv], cwd=cwd, env=env, capture_output=True, text=True
    )


def test_exported_tree_records_experiments_without_git(app_layout, capfd, tmp_path):
    """The container flow: create -> export -> git-less create --from-snapshot."""
    verstr = _recorded_dirty_state(app_layout, capfd)
    code = tmp_path / "image" / "code"
    records = tmp_path / "records"
    assert _export(app_layout, verstr, str(code)) == 0

    common = ["--from-snapshot", str(code), "--experiment-dir", str(records)]
    created = _vmn_exp_without_git(
        code.parent, "create", app_layout.app_name, *common, "--note", "in the container"
    )
    assert created.returncode == 0, created.stderr
    listed = _vmn_exp_without_git(code.parent, "list", app_layout.app_name, *common)
    assert listed.returncode == 0, listed.stderr
    assert "in the container" in listed.stdout
