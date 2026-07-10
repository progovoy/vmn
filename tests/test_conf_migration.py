import os
import subprocess

import git

from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger

from helpers import (
    _init_app,
    _run_vmn_init,
    _stamp_app,
)


def _vmn_status_clean(repo_path):
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--", ".vmn"],
        cwd=repo_path,
    ).decode()
    return status.strip() == ""


def _last_commit_files(repo_path):
    be = git.Repo(repo_path)
    try:
        return set(be.head.commit.stats.files.keys())
    finally:
        be.close()


def test_stamp_migrates_flat_conf_on_current_branch(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    branch = "b2"
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat_conf_path = os.path.join(app_dir, f"{branch}_conf.yml")
    canonical_conf_path = os.path.join(app_dir, "branch_conf", branch, "conf.yml")

    app_layout.write_conf(
        flat_conf_path, template="[test_{major}][.{minor}][.{patch}]"
    )

    subprocess.call(["git", "checkout", "-b", branch], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    assert not os.path.exists(flat_conf_path)
    assert os.path.exists(canonical_conf_path)
    assert _vmn_status_clean(app_layout.repo_path)

    # The stamp commit tracks the canonical conf and no longer the flat one.
    tracked = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=app_layout.repo_path,
    ).decode().split()
    rel_flat = os.path.relpath(flat_conf_path, app_layout.repo_path)
    rel_canon = os.path.relpath(canonical_conf_path, app_layout.repo_path)
    assert rel_canon in tracked
    assert rel_flat not in tracked


def test_stamp_migrates_legacy_nested_conf(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    branch = "a/b/c"
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    legacy_conf_path = os.path.join(app_dir, "a", "b", "c_conf.yml")
    canonical_conf_path = os.path.join(
        app_dir, "branch_conf", "a", "b", "c", "conf.yml"
    )

    os.makedirs(os.path.dirname(legacy_conf_path), exist_ok=True)
    app_layout.write_conf(
        legacy_conf_path, template="[test_{major}][.{minor}][.{patch}]"
    )

    subprocess.call(["git", "checkout", "-b", branch], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    assert not os.path.exists(legacy_conf_path)
    assert os.path.exists(canonical_conf_path)
    # Emptied legacy subdirs are removed.
    assert not os.path.isdir(os.path.join(app_dir, "a"))
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migrates_root_conf(app_layout):
    _run_vmn_init()
    _init_app("root_app/svc1")
    _stamp_app("root_app/svc1", "patch")

    branch = "b2"
    root_dir = os.path.join(app_layout.repo_path, ".vmn", "root_app")
    flat_root_conf = os.path.join(root_dir, f"{branch}_root_conf.yml")
    canonical_root_conf = os.path.join(
        root_dir, "branch_conf", branch, "root_conf.yml"
    )

    with open(flat_root_conf, "w") as f:
        f.write("conf:\n  external_services: {}\n")
    app_layout._app_backend.add_conf_file(flat_root_conf)

    subprocess.call(["git", "checkout", "-b", branch], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app("root_app/svc1", "patch")
    assert err == 0

    assert not os.path.exists(flat_root_conf)
    assert os.path.exists(canonical_root_conf)
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migrates_all_apps(app_layout):
    _run_vmn_init()
    _init_app("app_a")
    _stamp_app("app_a", "patch")
    _init_app("app_b")
    _stamp_app("app_b", "patch")

    branch = "b2"
    dir_a = os.path.join(app_layout.repo_path, ".vmn", "app_a")
    dir_b = os.path.join(app_layout.repo_path, ".vmn", "app_b")
    flat_a = os.path.join(dir_a, f"{branch}_conf.yml")
    flat_b = os.path.join(dir_b, f"{branch}_conf.yml")
    canon_a = os.path.join(dir_a, "branch_conf", branch, "conf.yml")
    canon_b = os.path.join(dir_b, "branch_conf", branch, "conf.yml")

    app_layout.write_conf(flat_a, template="[a_{major}]")
    app_layout.write_conf(flat_b, template="[b_{major}]")

    subprocess.call(["git", "checkout", "-b", branch], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    # Stamp only app_a; app_b's conf should also migrate.
    err, _, _ = _stamp_app("app_a", "patch")
    assert err == 0

    assert not os.path.exists(flat_a)
    assert os.path.exists(canon_a)
    assert not os.path.exists(flat_b)
    assert os.path.exists(canon_b)
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migration_prefers_flat_over_legacy_when_canonical_exists(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    branch = "feat/x"
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    canonical_conf_path = os.path.join(
        app_dir, "branch_conf", "feat", "x", "conf.yml"
    )
    flat_conf_path = os.path.join(app_dir, "feat-x_conf.yml")
    legacy_conf_path = os.path.join(app_dir, "feat", "x_conf.yml")

    os.makedirs(os.path.dirname(canonical_conf_path), exist_ok=True)
    app_layout.write_conf(canonical_conf_path, template="[canon_{major}]")
    app_layout.write_conf(flat_conf_path, template="[flat_{major}]")
    os.makedirs(os.path.dirname(legacy_conf_path), exist_ok=True)
    app_layout.write_conf(legacy_conf_path, template="[legacy_{major}]")

    subprocess.call(
        ["git", "checkout", "-b", branch], cwd=app_layout.repo_path
    )
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Canonical content survives; the lower-precedence duplicates are gone,
    # including the emptied legacy directory tree.
    with open(canonical_conf_path) as f:
        assert "canon_" in f.read()
    assert not os.path.exists(flat_conf_path)
    assert not os.path.exists(legacy_conf_path)
    assert not os.path.isdir(os.path.join(app_dir, "feat"))
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migration_flat_wins_over_legacy(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    branch = "feat/x"
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat_conf_path = os.path.join(app_dir, "feat-x_conf.yml")
    legacy_conf_path = os.path.join(app_dir, "feat", "x_conf.yml")
    canonical_conf_path = os.path.join(
        app_dir, "branch_conf", "feat", "x", "conf.yml"
    )

    app_layout.write_conf(flat_conf_path, template="[flat_{major}]")
    os.makedirs(os.path.dirname(legacy_conf_path), exist_ok=True)
    app_layout.write_conf(legacy_conf_path, template="[legacy_{major}]")

    subprocess.call(
        ["git", "checkout", "-b", branch], cwd=app_layout.repo_path
    )
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(canonical_conf_path) as f:
        assert "flat_" in f.read()
    assert not os.path.exists(flat_conf_path)
    assert not os.path.exists(legacy_conf_path)
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migration_dashed_flat_conf_converts_to_slashed_branch(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    # Even when a literal "a-b" branch collides on the prefix, the slashed
    # branch interpretation wins: a-b_conf.yml -> branch_conf/a/b/conf.yml.
    subprocess.call(["git", "branch", "a-b"], cwd=app_layout.repo_path)

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat_conf_path = os.path.join(app_dir, "a-b_conf.yml")
    canonical_conf_path = os.path.join(app_dir, "branch_conf", "a", "b", "conf.yml")
    app_layout.write_conf(flat_conf_path, template="[amb_{major}]")

    subprocess.call(["git", "checkout", "-b", "a/b"], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    assert not os.path.exists(flat_conf_path)
    assert os.path.exists(canonical_conf_path)
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migration_multiple_slashed_matches_skipped(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    # Two slashed branches whose dashed forms collide on prefix "x-y-z":
    # no safe target, so the flat conf stays readable via the flat layout.
    subprocess.call(["git", "branch", "x/y-z"], cwd=app_layout.repo_path)
    subprocess.call(["git", "branch", "x-y/z"], cwd=app_layout.repo_path)

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat_conf_path = os.path.join(app_dir, "x-y-z_conf.yml")
    app_layout.write_conf(flat_conf_path, template="[amb_{major}]")

    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    assert os.path.exists(flat_conf_path)
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_migration_deleted_branch_prefix_then_pruned(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    # No branch named "gone" exists -> dashes are treated literally.
    flat_conf_path = os.path.join(app_dir, "gone_conf.yml")
    canonical_conf_path = os.path.join(
        app_dir, "branch_conf", "gone", "conf.yml"
    )
    app_layout.write_conf(flat_conf_path, template="[gone_{major}]")

    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Migrated to canonical for branch "gone", then pruned as an other-branch conf.
    assert not os.path.exists(flat_conf_path)
    assert not os.path.exists(canonical_conf_path)
    assert not os.path.isdir(os.path.join(app_dir, "branch_conf"))
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_dry_run_does_not_migrate(app_layout, caplog):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    branch = "b2"
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat_conf_path = os.path.join(app_dir, f"{branch}_conf.yml")
    canonical_conf_path = os.path.join(app_dir, "branch_conf", branch, "conf.yml")
    app_layout.write_conf(flat_conf_path, template="[test_{major}]")

    subprocess.call(["git", "checkout", "-b", branch], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    reset_logger()
    ret = vmn_run(["stamp", "-r", "patch", "--dry-run", app_layout.app_name])[0]
    assert ret == 0

    assert os.path.exists(flat_conf_path)
    assert not os.path.exists(canonical_conf_path)


def test_stamp_migration_idempotent(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    branch = "b2"
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat_conf_path = os.path.join(app_dir, f"{branch}_conf.yml")
    canonical_conf_path = os.path.join(app_dir, "branch_conf", branch, "conf.yml")
    app_layout.write_conf(flat_conf_path, template="[test_{major}]")

    subprocess.call(["git", "checkout", "-b", branch], cwd=app_layout.repo_path)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert os.path.exists(canonical_conf_path)

    app_layout.write_file_commit_and_push("test_repo_0", "b.txt", "bv")
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    files = _last_commit_files(app_layout.repo_path)
    # Second stamp touches no branch_conf paths.
    assert not any("branch_conf" in f for f in files)
    assert _vmn_status_clean(app_layout.repo_path)


def test_stamp_removes_other_branch_canonical_conf(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)

    other_branch = "b2"
    other_canonical = os.path.join(
        app_dir, "branch_conf", other_branch, "conf.yml"
    )
    os.makedirs(os.path.dirname(other_canonical), exist_ok=True)
    app_layout.write_conf(other_canonical, template="[test_{major}]")

    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "bv")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # Stamping on main removes the other branch's canonical conf.
    assert not os.path.exists(other_canonical)
    assert not os.path.isdir(os.path.join(app_dir, "branch_conf"))
    assert _vmn_status_clean(app_layout.repo_path)
