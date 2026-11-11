"""Build the flat ``experiment`` parser from its flag groups.

Each group is applied once, in :data:`GROUPS` order (which is also the order
of ``--help``); :data:`.actions.ACTION_FLAGS` says which action owns which.
"""
import argparse

from vmn_exp.cli.define_metric_args import add_define_metric_flags
from vmn_exp.cli.exp_parser import (
    flags_create as create,
    flags_list as listing,
    flags_misc as misc,
    flags_mlflow,
    flags_prune,
    flags_rerun,
    flags_run,
    flags_select as select,
    flags_storage,
)
from vmn_exp.cli.exp_parser.actions import ACTION_FLAGS, EXPERIMENT_ACTIONS
from vmn_exp.cli.finish_args import add_finish_flags
from vmn_exp.cli.intent_arg import add_intent_flags
from vmn_exp.cli.similar_args import add_similar_flags, add_similar_hint_flag
from vmn_exp.cli.sweep.parser import add_experiment_storage_flags

GROUPS = {
    "name": create.add_name,
    "new_app": create.add_new_app,
    "tag": misc.add_tag,
    "archived": select.add_archived,
    "version": select.add_version,
    "note": create.add_note,
    "file": create.add_file,
    "metrics": create.add_metrics,
    "attach": create.add_attach,
    "sort": listing.add_sort,
    "importance": misc.add_importance,
    "top": listing.add_top,
    "last": select.add_last,
    "latest": select.add_latest,
    "diff": misc.add_diff,
    "output": misc.add_output,
    "prune": flags_prune.add_prune,
    "dry_run": misc.add_dry_run,
    "push": misc.add_push,
    "rerun": flags_rerun.add_rerun,
    "force": misc.add_force,
    "show": misc.add_show,
    "query": select.add_query,
    "json": select.add_json,
    "from_snapshot": flags_storage.add_from_snapshot,
    "capture_env": create.add_capture_env,
    "inputs": create.add_inputs,
    "supervision": flags_run.add_supervision,
    "watch": misc.add_watch,
    "export_metrics": misc.add_export_metrics,
    "compact": misc.add_compact,
    "all_apps": misc.add_all_apps,
    "lineage": misc.add_lineage,
    "parent": create.add_parent,
    "fork": create.add_fork,
    "rewind": misc.add_rewind,
    "storage": add_experiment_storage_flags,
    "define_metric": add_define_metric_flags,
    "finish": add_finish_flags,
    "intent": add_intent_flags,
    "similar": add_similar_flags,
    "similar_hint": add_similar_hint_flag,
    "mlflow": flags_mlflow.add_mlflow,
}


def add_experiment_parser(subparsers, name):
    pexp = subparsers.add_parser(
        name, help="Experiment tracking for reproducible research"
    )
    pexp.set_defaults(strict_version=False)
    pexp.add_argument(
        "action", nargs="?", default="create",
        choices=EXPERIMENT_ACTIONS,
        help="Experiment action (default: create)",
    )
    add_positionals(pexp)
    for add_group in GROUPS.values():
        add_group(pexp)


def add_positionals(parser):
    """The app name and the run refs every action takes."""
    parser.add_argument("name", help="The application's name")
    parser.add_argument("refs", nargs="*", default=None,
                        help="tag/archive/unarchive: run refs (verstr, prefix, @N, latest); "
                             "tag also takes key=value pairs")


def group_flags(group):
    """The option strings *group* adds."""
    parser = argparse.ArgumentParser(add_help=False)
    GROUPS[group](parser)
    return {flag for action in parser._actions for flag in action.option_strings}


def flag_defaults():
    """``{dest: (option, default, group)}`` for every flag, built now: some
    defaults read a module value when the parser is built (``--max-bytes``)."""
    defaults = {}
    for group, add_group in GROUPS.items():
        parser = argparse.ArgumentParser(add_help=False)
        add_group(parser)
        for action in parser._actions:
            option = max(action.option_strings, key=len)
            defaults[action.dest] = (option, parser.get_default(action.dest), group)
    return defaults


def owned_flags(action):
    """Every option string *action* owns."""
    return set().union(*(group_flags(group) for group in ACTION_FLAGS[action]))
