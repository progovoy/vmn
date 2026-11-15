"""Reject a flag the experiment action does not own (plan 39 B5b) and run refs
on an action that takes none (B7).

The flat parser accepts every flag on every action; this check runs right
after parsing, before the repo or a store is touched.
"""
from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.exp_parser.actions import ACTION_FLAGS, MANAGE_ACTIONS
from vmn_exp.cli.exp_parser.build import flag_defaults

USAGE_ERROR = 2


def foreign_flags(args, action, defaults, action_flags):
    """The options set away from their default whose group *action* does not own.

    *defaults* is ``{dest: (option, default, group)}``; a flag passed with its
    default value is indistinguishable from not passing it, so it is not named.
    """
    owned = action_flags[action]
    return sorted(
        option for dest, (option, default, group) in defaults.items()
        if group not in owned and getattr(args, dest, default) != default
    )


def foreign_flags_message(action, flags):
    named = ", ".join(f"'{flag}'" for flag in flags)
    verb = "is not a flag" if len(flags) == 1 else "are not flags"
    return f"{named} {verb} of 'vmn-exp {action}' (see 'vmn-exp {action} --help')"


def refuse_foreign_flags(args):
    """``2`` (and logged) when *args* sets a flag its action does not own, else None."""
    flags = foreign_flags(args, args.action, flag_defaults(), ACTION_FLAGS)
    if not flags:
        return None
    VMN_LOGGER.error(foreign_flags_message(args.action, flags))
    return USAGE_ERROR


def refuse_stray_refs(args):
    """``2`` (and logged) when an action that takes no refs was given some, else None."""
    stray = getattr(args, "refs", None)
    if not stray or args.action in MANAGE_ACTIONS:
        return None
    VMN_LOGGER.error(f"Unexpected arguments for 'vmn-exp {args.action}': {' '.join(stray)}")
    return USAGE_ERROR


def refuse_usage_errors(args):
    """``2`` when the experiment invocation is wrong (a foreign flag, stray refs)."""
    return refuse_foreign_flags(args) or refuse_stray_refs(args)
