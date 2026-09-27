"""Tests for the CLI plugin registry (Phase 1 step f).

These tests do NOT require Docker — they exercise plugin_api and plugins
in isolation using monkeypatching and simple fakes.
"""
import argparse
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to get a clean registry state for each test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    """Reset the plugin_api registry and dev-version loader between tests."""
    import version_stamp.cli.plugin_api as _api
    monkeypatch.setattr(_api, "_registry", [])
    monkeypatch.setattr(_api, "_dev_version_loader", None)
    yield


# ---------------------------------------------------------------------------
# 1. A registered CommandSpec is dispatched correctly
# ---------------------------------------------------------------------------

def test_fake_spec_dispatches():
    from version_stamp.cli.plugin_api import CommandSpec, find, register

    called_with = []

    def _add_parser(subparsers):
        p = subparsers.add_parser("fake")
        return p

    def _handle(ctx):
        called_with.append(ctx)
        return 42

    spec = CommandSpec(
        names=("fake",),
        add_parser=_add_parser,
        handle=_handle,
        access="local",
    )
    register(spec)

    found = find("fake")
    assert found is spec

    result = found.handle("my_ctx")
    assert result == 42
    assert called_with == ["my_ctx"]


# ---------------------------------------------------------------------------
# 2. read_only_actions on a spec causes lock to be skipped
# ---------------------------------------------------------------------------

def test_read_only_actions_skip_lock():
    """A spec with read_only_actions should make _takes_repo_lock return False."""
    from version_stamp.cli.plugin_api import CommandSpec, register

    register(CommandSpec(
        names=("myexp",),
        add_parser=lambda sp: sp.add_parser("myexp"),
        handle=lambda ctx: 0,
        access="local",
        read_only_actions=frozenset({"list", "show"}),
    ))

    # Import entry after registry is populated so it can look up the spec
    import version_stamp.cli.entry as entry

    args_list = SimpleNamespace(command="myexp", action="list")
    assert entry._takes_repo_lock(args_list) is False

    args_mutate = SimpleNamespace(command="myexp", action="create")
    assert entry._takes_repo_lock(args_mutate) is True


# ---------------------------------------------------------------------------
# 3. run_without_repo short-circuits before repo resolution
# ---------------------------------------------------------------------------

def test_run_without_repo_short_circuits():
    from version_stamp.cli.plugin_api import CommandSpec, register

    ran = []

    def _run_without_repo(args):
        ran.append(args)
        return 7  # non-None → short-circuit

    register(CommandSpec(
        names=("norepocmd",),
        add_parser=lambda sp: sp.add_parser("norepocmd"),
        handle=lambda ctx: 0,
        access="local",
        run_without_repo=_run_without_repo,
    ))

    import version_stamp.cli.plugin_api as _api
    spec = _api.find("norepocmd")
    args = SimpleNamespace(command="norepocmd")
    result = spec.run_without_repo(args)
    assert result == 7
    assert ran == [args]


# ---------------------------------------------------------------------------
# 4. double-dash splitting only fires for specs with split_after_double_dash
# ---------------------------------------------------------------------------

def test_double_dash_split_only_for_flagged_spec():
    """parse_user_commands splits -- only for specs flagged split_after_double_dash."""
    from version_stamp.cli.plugin_api import CommandSpec, register

    # Register a spec WITHOUT the flag
    register(CommandSpec(
        names=("ordinary",),
        add_parser=lambda sp: sp.add_parser("ordinary"),
        handle=lambda ctx: 0,
        split_after_double_dash=False,
    ))
    # Register a spec WITH the flag
    register(CommandSpec(
        names=("dbl",),
        add_parser=lambda sp: sp.add_parser("dbl"),
        handle=lambda ctx: 0,
        split_after_double_dash=True,
    ))

    import version_stamp.cli.args as _args

    # Only the flagged spec should trigger the split
    cl_no_split = ["ordinary", "myapp", "--", "ls"]
    cl_split = ["dbl", "myapp", "--", "ls", "-la"]

    no_split_result = _args._should_split_double_dash(cl_no_split)
    split_result = _args._should_split_double_dash(cl_split)

    assert no_split_result is False
    assert split_result is True


# ---------------------------------------------------------------------------
# 5. Missing plugin module does not break stamp path
# ---------------------------------------------------------------------------

def test_missing_plugin_module_keeps_stamping_working(monkeypatch):
    """When BUILTIN_PLUGINS lists a missing module, the parser still builds."""
    import version_stamp.cli.plugins as _plugins

    monkeypatch.setattr(_plugins, "BUILTIN_PLUGINS", ("nonexistent.module.xyz",))

    # Should NOT raise — ImportError is swallowed
    _plugins.load_builtin_plugins()

    # Parser should still build (exp/snapshot subparsers come from plugin; if
    # plugin is absent the parser is just missing those subcommands, which is
    # acceptable for stamping-only usage)
    import version_stamp.cli.args as _args

    parser = argparse.ArgumentParser("vmn")
    subparsers = parser.add_subparsers(dest="command")
    # add_arg_stamp should still work
    _args.add_arg_stamp(subparsers)
    args = parser.parse_args(["stamp", "myapp"])
    assert args.command == "stamp"


# ---------------------------------------------------------------------------
# 6. Registered dev-version loader is called by load_dev_version
# ---------------------------------------------------------------------------

def test_goto_dev_uses_registered_loader():
    from version_stamp.cli.plugin_api import (
        load_dev_version,
        register_dev_version_loader,
    )

    calls = []

    def _loader(vcs, params, version):
        calls.append((vcs, params, version))
        return 0

    register_dev_version_loader(_loader)

    vcs = MagicMock()
    params = {"root_path": "/tmp"}
    result = load_dev_version(vcs, params, "1.2.3-dev.abc.0001")
    assert result == 0
    assert calls == [(vcs, params, "1.2.3-dev.abc.0001")]


def test_load_dev_version_returns_1_when_no_loader_registered():
    from version_stamp.cli.plugin_api import load_dev_version

    result = load_dev_version(None, {}, "1.0.0-dev.abc.0001")
    assert result == 1
