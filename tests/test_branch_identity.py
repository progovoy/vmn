"""active_branch is the branch identity, local_branch the git ref (plan 17 F2)."""
from island_helpers import (  # noqa: F401 (_no_ci_env is an autouse fixture)
    _ci_checkout,
    _commit,
    _head,
    _no_ci_env,
    _out,
    _stamped_repo,
)
from helpers import _stamp_app
from version_stamp.backends.git import GitBackend
from version_stamp.core.constants import LEGACY_TRACKING_PREFIX
from version_stamp.devversion.capture import _generate_patches


def _on_legacy_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    legacy = f"{LEGACY_TRACKING_PREFIX}origin_{default}__from_abcde"
    _out(repo, "checkout", "-q", "-b", legacy, "--track", f"origin/{default}")
    return repo, default, legacy


def test_legacy_branch_identity_is_its_upstream_and_ref_is_local(app_layout):
    repo, default, legacy = _on_legacy_branch(app_layout)

    backend = GitBackend(repo)

    assert backend.active_branch == default
    assert backend.local_branch == legacy


def test_outgoing_check_on_a_legacy_branch_uses_the_local_ref(app_layout):
    repo, default, legacy = _on_legacy_branch(app_layout)
    _commit(repo, "unpushed.txt")

    err = GitBackend(repo).check_for_outgoing_changes()

    assert err is not None
    assert f"from branch {legacy}" in err


def test_dev_patches_on_a_legacy_branch_use_the_local_ref(app_layout):
    repo, default, legacy = _on_legacy_branch(app_layout)
    _commit(repo, "unpushed.txt")

    patches = _generate_patches(GitBackend(repo), lightweight=True)

    assert "unpushed.txt" in patches.get("local_commits", "")


def test_stamp_on_a_legacy_branch_pushes_the_local_ref_to_its_upstream(app_layout):
    repo, default, legacy = _on_legacy_branch(app_layout)
    _commit(repo, "f1.file")
    _out(repo, "push", "-q", "origin", f"HEAD:refs/heads/{default}")

    assert _stamp_app(app_layout.app_name, "patch")[0] == 0

    assert _out(repo, "rev-parse", f"origin/{default}") == _head(repo)
    assert _out(repo, "branch", "--show-current") == legacy


def test_normal_branch_identity_and_ref_are_equal(app_layout):
    repo, default, _ = _stamped_repo(app_layout)

    backend = GitBackend(repo)

    assert backend.active_branch == backend.local_branch == default


def test_detached_ci_checkout_identity_and_ref_are_the_resolved_branch(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    _ci_checkout(repo, default)

    backend = GitBackend(repo)

    assert backend.active_branch == backend.local_branch == default
