"""vmn-exp reuses vmn's snapshot helpers through version_stamp.api."""
from version_stamp import api


def test_experiment_cli_uses_the_api_relative_timestamp():
    import vmn_exp.cli.experiment as experiment
    import vmn_exp.snapshot as exp_snapshot

    assert experiment.relative_timestamp is api.relative_timestamp
    assert not hasattr(exp_snapshot, "_relative_timestamp")


def test_experiment_export_uses_the_api_export_tree():
    import vmn_exp.cli.experiment as experiment

    assert experiment.export_tree is api.export_tree
