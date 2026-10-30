#!/usr/bin/env python3
"""``vmn-exp tag`` / ``archive`` / ``unarchive``: change stored runs.

::

    vmn-exp tag my_app @3 stage=prod owner=ann --remove todo
    vmn-exp archive my_app @1 @2
    vmn-exp unarchive my_app @2
    vmn-exp archive my_app --query 'tags.batch = "old"' [--dry-run]

Positionals after the app name are run refs (a verstr, a unique prefix, ``@N``
or ``latest``) and, for ``tag``, ``key=value`` pairs — a verstr never contains
``=``, so the two cannot be confused. ``-v``/``--latest`` name a run too.
``archive``/``unarchive --query`` act on every run the query selects instead
(:func:`vmn_exp.sdk.manage.archive_runs`) and print a count.
Neither ever touches a run's results (metrics, log history, artifacts):
see :mod:`vmn_exp.core.manage`.
"""
from vmn_exp.cli.prune_query import print_preview
from vmn_exp.core.manage import set_archived, tag_run
from vmn_exp.core.query import QueryError
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.sdk import manage
from version_stamp.api import VMN_LOGGER

MANAGE_ACTIONS = ("tag", "archive", "unarchive")
DRY_RUN_SAMPLE = 10


def refuse_stray_refs(args):
    """True (and logged) when an action that takes no refs was given some."""
    stray = getattr(args, "refs", None)
    if stray and args.action not in MANAGE_ACTIONS:
        VMN_LOGGER.error(f"Unexpected arguments for 'exp {args.action}': {' '.join(stray)}")
        return True
    return False


def _split_refs(args):
    """``(refs, {key: value})`` from the positionals, plus ``-v``/``--latest``."""
    positional = getattr(args, "refs", None) or []
    refs = [p for p in positional if "=" not in p] + list(args.version or [])
    if getattr(args, "latest", False):
        refs.append("latest")
    pairs = [p.split("=", 1) for p in positional if "=" in p]
    return refs, dict(pairs)


def _resolved(storage, app_name, refs):
    """The verstrs *refs* name, or None (logged) if any names nothing."""
    verstrs = []
    for ref in refs:
        verstr, err = resolve_experiment(storage, app_name, ref)
        if err:
            VMN_LOGGER.error(err)
            return None
        verstrs.append(verstr)
    return verstrs


def _archive(storage, app_name, verstrs, archived):
    for verstr in verstrs:
        if not set_archived(storage, app_name, verstr, archived):
            VMN_LOGGER.error(f"Experiment '{verstr}' not found for {app_name}")
            return 1
        print(verstr)
    return 0


def _tag(storage, app_name, verstrs, tags, remove):
    if len(verstrs) != 1:
        VMN_LOGGER.error("exp tag takes exactly one run (a ref, -v or --latest)")
        return 1
    try:
        done = tag_run(storage, app_name, verstrs[0], tags, remove)
    except ValueError as e:
        VMN_LOGGER.error(str(e))
        return 1
    if not done:
        VMN_LOGGER.error(f"Experiment '{verstrs[0]}' not found for {app_name}")
        return 1
    print(verstrs[0])
    return 0


def _archive_by_query(storage, app_name, args):
    verb = args.action
    bulk = manage.archive_runs if verb == "archive" else manage.unarchive_runs
    try:
        verstrs = bulk(app_name, args.query, storage=storage, dry_run=args.dry_run)
    except QueryError as e:
        VMN_LOGGER.error(f"Invalid --query: {e}")
        return 1
    if not args.dry_run:
        print(f"{verb.capitalize()}d {len(verstrs)} run(s)")
        return 0
    print_preview(f"Would {verb} {len(verstrs)} run(s)", verstrs, DRY_RUN_SAMPLE)
    return 0


def experiment_manage(app_name, storage, args):
    refs, tags = _split_refs(args)
    if getattr(args, "query", None) is not None and args.action != "tag":
        if refs or tags:
            VMN_LOGGER.error(f"exp {args.action} takes runs or --query, not both")
            return 1
        return _archive_by_query(storage, app_name, args)
    if not refs:
        VMN_LOGGER.error(f"exp {args.action} needs a run: a ref, -v or --latest")
        return 1
    verstrs = _resolved(storage, app_name, refs)
    if verstrs is None:
        return 1
    if args.action == "tag":
        return _tag(storage, app_name, verstrs, tags, getattr(args, "remove", None))
    if tags:
        VMN_LOGGER.error(f"exp {args.action} takes runs, not key=value pairs")
        return 1
    return _archive(storage, app_name, verstrs, args.action == "archive")
