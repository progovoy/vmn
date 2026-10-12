"""Commands declare that they commit; one stamper ensure_on_branch (plan 17 F6)."""
import os

import pytest

from helpers import _stamp_app
from island_helpers import (  # noqa: F401 (_no_ci_env is an autouse fixture)
    _ci_checkout,
    _commit,
    _current,
    _no_ci_env,
    _out,
    _stamped_repo,
)
from version_stamp.cli import plugin_api
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from version_stamp.core.utils import branch_conf_canonical_path


@pytest.fixture
def _plugin(monkeypatch):
    """Register a no-op `fake` plugin command; returns a setter for `commits`."""
    monkeypatch.setattr(plugin_api, "_registry", [])

    def register(commits):
        def add_parser(subparsers):
            parser = subparsers.add_parser("fake")
            parser.add_argument("name")
            return parser

        plugin_api.register(
            plugin_api.CommandSpec(
                names=("fake",),
                add_parser=add_parser,
                handle=lambda ctx: 0,
                commits=commits,
            )
        )

    return register


def _ci_checkout_at_remote_tip(app_layout):
    repo, default, _ = _stamped_repo(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    _ci_checkout(repo, default)
    return repo, default


def _run_fake(app_name):
    reset_logger()
    return vmn_run(["fake", app_name])[0]


def test_plugin_that_commits_lands_on_the_branch(app_layout, _plugin):
    repo, default = _ci_checkout_at_remote_tip(app_layout)
    _plugin(commits=True)

    assert _run_fake(app_layout.app_name) == 0

    assert _current(repo) == default


def test_plugin_commits_may_depend_on_its_args(app_layout, _plugin):
    repo, default = _ci_checkout_at_remote_tip(app_layout)
    _plugin(commits=lambda args: args.name == app_layout.app_name)

    assert _run_fake(app_layout.app_name) == 0

    assert _current(repo) == default


def test_plugin_that_does_not_commit_stays_detached(app_layout, _plugin):
    repo, _ = _ci_checkout_at_remote_tip(app_layout)
    _plugin(commits=False)

    assert _run_fake(app_layout.app_name) == 0

    assert _current(repo) == ""


def _stamper(app_name):
    reset_logger()
    return vmn_run(["show", app_name])[1].vcs


def test_stamper_ensure_on_branch_reloads_the_new_branchs_conf(
    app_layout, monkeypatch
):
    repo, default, _ = _stamped_repo(app_layout)
    app_dir = os.path.join(repo, ".vmn", app_layout.app_name)
    rel_conf = branch_conf_canonical_path(app_dir, "rel")
    os.makedirs(os.path.dirname(rel_conf), exist_ok=True)
    with open(rel_conf, "w") as f:
        f.write('conf:\n  template: "[{major}]"\n')
    _out(repo, "add", rel_conf)
    _commit(repo, "rel.txt")
    _out(repo, "push", "-q", "origin", f"HEAD:refs/heads/{default}")
    _out(repo, "branch", "-q", "rel")
    _out(repo, "checkout", "-q", "--detach")
    vcs = _stamper(app_layout.app_name)
    assert vcs.app_conf_path != rel_conf

    def check_out_rel(require_tip, **_kwargs):
        _out(repo, "checkout", "-q", "rel")
        vcs.backend.active_branch = "rel"
        vcs.backend.detached_head = False
        return True

    monkeypatch.setattr(vcs.backend, "ensure_on_branch", check_out_rel)

    assert vcs.ensure_on_branch() is True

    assert vcs.app_conf_path == rel_conf
    assert vcs.raw_template == "[{major}]"


def test_stamper_ensure_on_branch_keeps_the_app_when_the_branch_is_the_same(
    app_layout,
):
    repo, default = _ci_checkout_at_remote_tip(app_layout)
    vcs = _stamper(app_layout.app_name)
    conf_path = vcs.app_conf_path

    assert vcs.ensure_on_branch() is True

    assert _current(repo) == default
    assert vcs.app_conf_path == conf_path


def test_stamp_from_a_ci_checkout_still_lands_on_the_branch(app_layout):
    repo, default = _ci_checkout_at_remote_tip(app_layout)

    assert _stamp_app(app_layout.app_name, "patch")[0] == 0

    assert _current(repo) == default
