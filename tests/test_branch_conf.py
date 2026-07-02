import os

from version_stamp.core.utils import (
    branch_conf_canonical_path,
    branch_conf_flat_path,
    branch_conf_legacy_path,
    resolve_branch_conf_path,
)


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("conf: {}\n")


def test_canonical_path_builds_nested_dirs_for_slashed_branch(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_canonical_path(app_dir, "topic/fix") == os.path.join(
        app_dir, "branch_conf", "topic", "fix", "conf.yml"
    )
    assert branch_conf_canonical_path(app_dir, "master") == os.path.join(
        app_dir, "branch_conf", "master", "conf.yml"
    )


def test_canonical_path_root_variant(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_canonical_path(app_dir, "topic/fix", root=True) == os.path.join(
        app_dir, "branch_conf", "topic", "fix", "root_conf.yml"
    )


def test_flat_path_dashes_slashes(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_flat_path(app_dir, "topic/fix") == os.path.join(
        app_dir, "topic-fix_conf.yml"
    )
    assert branch_conf_flat_path(app_dir, "topic/fix", root=True) == os.path.join(
        app_dir, "topic-fix_root_conf.yml"
    )


def test_legacy_path_nests_all_but_leaf(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_legacy_path(app_dir, "a/b/c") == os.path.join(
        app_dir, "a", "b", "c_conf.yml"
    )
    assert branch_conf_legacy_path(app_dir, "master") == os.path.join(
        app_dir, "master_conf.yml"
    )
    assert branch_conf_legacy_path(app_dir, "a/b", root=True) == os.path.join(
        app_dir, "a", "b_root_conf.yml"
    )


def test_resolve_prefers_canonical_over_flat_over_legacy(tmp_path):
    app_dir = str(tmp_path)
    branch = "a/b/c"
    _touch(branch_conf_canonical_path(app_dir, branch))
    _touch(branch_conf_flat_path(app_dir, branch))
    _touch(branch_conf_legacy_path(app_dir, branch))

    path, convention = resolve_branch_conf_path(app_dir, branch)
    assert path == branch_conf_canonical_path(app_dir, branch)
    assert convention == "canonical"


def test_resolve_flat_wins_over_legacy(tmp_path):
    app_dir = str(tmp_path)
    branch = "a/b/c"
    _touch(branch_conf_flat_path(app_dir, branch))
    _touch(branch_conf_legacy_path(app_dir, branch))

    path, convention = resolve_branch_conf_path(app_dir, branch)
    assert path == branch_conf_flat_path(app_dir, branch)
    assert convention == "flat"


def test_resolve_legacy_nested_detected(tmp_path):
    app_dir = str(tmp_path)
    branch = "a/b/c"
    _touch(branch_conf_legacy_path(app_dir, branch))

    path, convention = resolve_branch_conf_path(app_dir, branch)
    assert path == branch_conf_legacy_path(app_dir, branch)
    assert convention == "legacy"


def test_resolve_falls_back_to_default_conf(tmp_path):
    app_dir = str(tmp_path)
    _touch(os.path.join(app_dir, "conf.yml"))

    path, convention = resolve_branch_conf_path(app_dir, "no/such/branch")
    assert path == os.path.join(app_dir, "conf.yml")
    assert convention is None

    for empty_branch in (None, ""):
        path, convention = resolve_branch_conf_path(app_dir, empty_branch)
        assert path == os.path.join(app_dir, "conf.yml")
        assert convention is None


def test_resolve_root_conf_variants(tmp_path):
    app_dir = str(tmp_path)
    branch = "topic/fix"
    _touch(branch_conf_canonical_path(app_dir, branch, root=True))

    path, convention = resolve_branch_conf_path(app_dir, branch, root=True)
    assert path == branch_conf_canonical_path(app_dir, branch, root=True)
    assert convention == "canonical"

    path, convention = resolve_branch_conf_path(app_dir, "other", root=True)
    assert path == os.path.join(app_dir, "root_conf.yml")
    assert convention is None


def test_canonical_path_for_branch_named_branch_conf(tmp_path):
    app_dir = str(tmp_path)
    _touch(branch_conf_canonical_path(app_dir, "branch_conf"))

    path, convention = resolve_branch_conf_path(app_dir, "branch_conf")
    assert path == os.path.join(
        app_dir, "branch_conf", "branch_conf", "conf.yml"
    )
    assert convention == "canonical"
