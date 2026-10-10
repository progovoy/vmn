"""A legacy vmn_tracking_remote__* branch counts as its upstream (plan 17 §2.4a)."""
import glob
import os

import yaml

from island_helpers import _out
from test_ensure_on_branch import LEGACY, _stamped_repo
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from version_stamp.core.utils import branch_conf_canonical_path


def _on_legacy_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    legacy = f"{LEGACY}origin_{default}__from_abcde"
    _out(repo, "checkout", "-q", "-b", legacy, "--track", f"origin/{default}")
    return repo, default, legacy


def test_config_branch_on_a_legacy_branch_edits_the_upstream_conf(
    app_layout, monkeypatch
):
    repo, default, legacy = _on_legacy_branch(app_layout)
    monkeypatch.setenv("EDITOR", "true")

    reset_logger()
    assert vmn_run(["config", app_layout.app_name, "--branch", "--vim"])[0] == 0

    app_dir = os.path.join(repo, ".vmn", app_layout.app_name)
    assert os.path.isfile(branch_conf_canonical_path(app_dir, default))
    assert not os.path.exists(branch_conf_canonical_path(app_dir, legacy))


def test_snapshot_on_a_legacy_branch_records_the_upstream_branch(app_layout):
    repo, default, _ = _on_legacy_branch(app_layout)
    with open(os.path.join(repo, "dirty.txt"), "w") as f:
        f.write("work in progress\n")

    reset_logger()
    assert vmn_run(["snapshot", "create", app_layout.app_name])[0] == 0

    (meta_path,) = glob.glob(
        os.path.join(repo, ".vmn", "store", "snapshots", "*", "*", "metadata.yml")
    )
    with open(meta_path) as f:
        assert yaml.safe_load(f)["branch"] == default
