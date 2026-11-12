"""cli/experiment.py is split by command (plan 44 G15). Tests and other
modules import names from, and patch names on, ``vmn_exp.cli.experiment``;
both keep working after the move."""
import argparse
from types import SimpleNamespace

import pytest

from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.random import FakeRandom
from similar_seed import seed, verstr
from version_stamp.cli.args import parse_user_commands
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli import experiment
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"

NAMES_IMPORTED_FROM_EXPERIMENT = (
    "experiment_list", "_describe_log_entry", "_app_name", "READ_ONLY_ACTIONS",
    "_get_experiment_storage", "_MetricsTailer", "load_run_state",
    "_resolve_experiment_version", "_resolve_experiment_bundles", "_format_list_row",
    "_list_rows", "_print_status_block", "_experiment_create_core",
    "_experiment_create_from_snapshot", "_resolve_parent", "_parse_notes_file",
    "_append_inputs", "auto_init", "experiment_storage_params", "handle_experiment",
    "relative_timestamp", "export_tree", "VMN_LOGGER", "experiment_add",
    "experiment_compact", "experiment_compare", "experiment_create", "experiment_diff",
    "experiment_export", "experiment_prune", "experiment_push", "experiment_restore",
    "experiment_rewind", "experiment_run", "experiment_show", "experiment_similar",
    "experiment_similar_backfill", "experiment_backfill_children",
)


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _args(**kw):
    return argparse.Namespace(name=APP, version=None, latest=False, json=False, **kw)


def test_experiment_module_still_exposes_the_names_tests_import():
    missing = [name for name in NAMES_IMPORTED_FROM_EXPERIMENT if not hasattr(experiment, name)]
    assert missing == []


@pytest.mark.parametrize("action, extra", [
    ("experiment_show", {}),
    ("experiment_export", {"output": "out"}),
    ("experiment_restore", {"force": False}),
    ("experiment_add", {"metrics": None, "note": None, "attach": None, "file": None}),
])
def test_patching_resolve_experiment_version_on_the_experiment_module_reaches_show_and_export(
    tmp_path, monkeypatch, action, extra
):
    calls = []
    monkeypatch.setattr(experiment, "_resolve_experiment_version",
                        lambda *a, **kw: calls.append(a) or (None, "patched"))
    console = (FakeConsole(),) if action in ("experiment_show", "experiment_export") else ()
    random = (FakeRandom(),) if action == "experiment_add" else ()
    clock = (FakeClock(),) if action in ("experiment_restore", "experiment_show") else ()
    assert getattr(experiment, action)(None, {}, _storage(tmp_path), _args(**extra), *console, *random,
                                       *clock) == 1
    assert len(calls) == 1


@pytest.mark.parametrize("action", ["experiment_compare", "experiment_diff"])
def test_patching_resolve_experiment_bundles_reaches_compare_and_diff(
    tmp_path, monkeypatch, action
):
    calls = []
    monkeypatch.setattr(experiment, "_resolve_experiment_bundles",
                        lambda *a, **kw: calls.append(a))
    assert getattr(experiment, action)(
        None, {}, _storage(tmp_path), _args(last=None), FakeConsole()
    ) == 1
    assert len(calls) == 1


def test_patching_load_run_state_on_the_experiment_module_reaches_show(
    tmp_path, monkeypatch, capsys
):
    storage = _storage(tmp_path)
    v = seed(storage, APP, verstr(1))
    reads = []
    monkeypatch.setattr(experiment, "load_run_state", lambda s, a, run: reads.append(run))
    experiment._print_status_block(storage, APP, v, storage.load_metadata(APP, v), print,
                                   now=FakeClock().now())
    assert reads == [v]
    assert "Status:" in capsys.readouterr().out


def test_patching_the_logger_on_the_experiment_module_reaches_list_rows(monkeypatch):
    warnings = []
    monkeypatch.setattr(experiment, "VMN_LOGGER", SimpleNamespace(warning=warnings.append))
    experiment._list_rows([], None, "no_such_metric", {})
    assert warnings == ["Sort key 'no_such_metric' not found in any experiment"]


@pytest.mark.parametrize("action, handler", [
    ("list", "experiment_list"), ("show", "experiment_show"),
    ("compare", "experiment_compare"), ("diff", "experiment_diff"),
    ("restore", "experiment_restore"), ("export", "experiment_export"),
    ("add", "experiment_add"), ("prune", "experiment_prune"),
])
def test_dispatch_resolves_handlers_through_the_experiment_module(monkeypatch, action, handler):
    got = []
    monkeypatch.setattr(experiment, "_open_checked_storage", lambda *a, **k: "storage")
    monkeypatch.setattr(experiment, handler, lambda *a, **k: got.append(a[2]) or 7)
    args = parse_user_commands(["exp", action, "my_app"])
    io = SimpleNamespace(console=FakeConsole(), random=FakeRandom(), clock=FakeClock())
    assert experiment.handle_experiment(SimpleNamespace(vcs=None, args=args), io) == 7
    assert got == ["storage"]
