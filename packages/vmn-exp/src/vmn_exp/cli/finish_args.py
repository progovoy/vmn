#!/usr/bin/env python3
"""``vmn-exp add <app> -v <ref> --finish <code> [--error <text>] [--end-reason
<text>] [--force]``: the CLI's ``vmn_exp.sdk.manage.finish_run``.

Writes the run's final state from outside it (see :mod:`vmn_exp.core.run_finish`),
after the add's other entries, so a ``--note`` lands before the run reads finished.
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.run_finish import FinishRefusedError, finish_run


def add_finish_flags(parser):
    parser.add_argument("--finish", dest="finish", type=int, default=None, metavar="CODE",
                        help="add: finish the run with exit code CODE without reopening "
                             "it (refused while it heartbeats elsewhere or once it "
                             "finished, unless --force)")
    parser.add_argument("--error", dest="finish_error", default=None, metavar="TEXT",
                        help="add --finish: the failure, recorded as the run's error")
    parser.add_argument("--end-reason", dest="end_reason", default=None, metavar="TEXT",
                        help="add --finish: why the run ended (the end_reason field)")


def finish_flags_error(args):
    """The message for ``--error``/``--end-reason`` without ``--finish``, else None."""
    if args.finish is None and (args.finish_error is not None or args.end_reason):
        return "--error and --end-reason need --finish <code>"
    return None


def apply_finish(storage, app_name, verstr, args):
    """Finish *verstr* when ``--finish`` asks to; 1 when refused, else 0."""
    if args.finish is None:
        return 0
    try:
        finish_run(storage, app_name, verstr, args.finish, error=args.finish_error,
                   end_reason=args.end_reason, force=args.force)
    except FinishRefusedError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    VMN_LOGGER.info(f"Finished {verstr} with exit code {args.finish}")
    return 0
