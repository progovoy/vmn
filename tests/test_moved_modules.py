"""The experiment modules moved into vmn_exp/; their old version_stamp paths are gone."""
import importlib
import sys


def test_old_experiment_paths_are_gone():
    """After h1/h2/h3 moves, the old module names are no longer importable."""
    # These are the PRE-MOVE names; they must not exist after the files were moved.
    old_names = [
        "version_stamp.cli.snapshot",
        "version_stamp.core.experiment_writer",
        "version_stamp.cli.snapshot_storage_s3",
        "version_stamp.exp",
        "version_stamp.exp.run",
    ]
    for old_name in old_names:
        # Remove any cached entry so we get a fresh import attempt
        sys.modules.pop(old_name, None)
        try:
            mod = importlib.import_module(old_name)
            raise AssertionError(
                f"Expected {old_name!r} to be unimportable after the move, "
                f"but got: {mod}"
            )
        except ModuleNotFoundError:
            pass  # expected


def test_worker_command_imports_new_path():
    """The index worker subprocess command uses vmn_exp.core.index_workers, not the old path."""
    workers = importlib.import_module("vmn_exp.core.index_workers")
    cmd = workers._worker_command()
    cmd_str = " ".join(cmd)
    assert "vmn_exp.core.index_workers" in cmd_str, (
        f"worker command does not reference vmn_exp.core.index_workers: {cmd}"
    )
    assert "version_stamp.core.experiment_index_workers" not in cmd_str, (
        f"worker command still references old path version_stamp.core.experiment_index_workers: {cmd}"
    )


def test_cli_experiment_old_path_gone():
    """After h4: version_stamp.cli.experiment* must not be importable."""
    old_names = [
        "version_stamp.cli.experiment",
        "version_stamp.cli.experiment_run",
        "version_stamp.cli.experiment_prune",
        "version_stamp.cli.experiment_prune_query",
        "version_stamp.cli.experiment_manage",
        "version_stamp.cli.experiment_supervisor",
        "version_stamp.cli.experiment_inputs_arg",
        "version_stamp.cli.experiment_provenance",
        "version_stamp.cli.experiment_views",
        "version_stamp.cli._builtin_exp_plugin",
    ]
    for old_name in old_names:
        sys.modules.pop(old_name, None)
        try:
            mod = importlib.import_module(old_name)
            raise AssertionError(
                f"Expected {old_name!r} to be unimportable after h4 move, "
                f"but got: {mod}"
            )
        except ModuleNotFoundError:
            pass  # expected


def test_ui_old_path_gone():
    """After h5: version_stamp.ui must not be importable."""
    old_names = [
        "version_stamp.ui",
        "version_stamp.ui.server",
        "version_stamp.ui.cli",
        "version_stamp.ui.readers",
    ]
    for old_name in old_names:
        sys.modules.pop(old_name, None)
        try:
            mod = importlib.import_module(old_name)
            raise AssertionError(
                f"Expected {old_name!r} to be unimportable after h5 move, "
                f"but got: {mod}"
            )
        except ModuleNotFoundError:
            pass  # expected
