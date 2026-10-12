"""``vmn-exp similar <app> [-v <ref> | --latest] [--top 10] [--all-apps]
[--query <expr>] [--context <text> | --context-file <path|->] [--text-only]
[--archived] [--json]``: has anyone run something like this before?

The past runs most like run *ref* — or, with no ``-v``/``--latest``, like the
current **working tree**, so you can ask before creating a run. ``similar`` is
the one action whose missing ref means the working tree (``show``/``restore``/
``export`` take the latest run), because it is mostly asked before submitting.
The run itself, its sweep and its reruns (same code, params and inputs; forks
are kept) are left out; a group (a sweep, the reruns of one config) shows as
its best run on the goal metric.

``--context`` is a text query combined with the target's code facts, its
text replacing the target's own; ``--text-only`` matches that text alone
(no working tree needed). ``--all-apps`` searches every app of the store,
each under its own metrics schema; ``--query`` narrows the candidates like
``list --query``. The target app's conf ``experiment.similar.weights``
overrides the signal weights for every app searched. Read-only and
lock-free. Output: :mod:`vmn_exp.cli.similar_output`; ``--json`` items:
:mod:`vmn_exp.core.similar_search`.
"""
from version_stamp.api import VMN_LOGGER
from vmn_exp.cli.similar_args import read_context
from vmn_exp.cli.similar_output import print_items
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.query import QueryError
from vmn_exp.core.similar_search import DEFAULT_TOP, conf_schema_of, find
from vmn_exp.gitmode import capture
from vmn_exp.gitmode.features import features_for_working_tree

NEEDS_A_TREE = (
    "similar without -v/--latest compares the working tree, which needs a git checkout: "
    "pass -v <ref> or --latest (or --context <text> --text-only)"
)


def experiment_similar(vcs, storage, app_name, args):
    context, err = read_context(args)
    if err is not None:
        return err
    err = _check_flags(vcs, args, context)
    if err is not None:
        VMN_LOGGER.error(err)
        return 1
    ref = _ref(args)
    if ref == "":  # find() takes an empty ref for the latest run, as the SDK does
        VMN_LOGGER.error(f"Experiment '' not found for {app_name}")
        return 1
    target = None
    if not (_has_ref(args) or args.text_only):
        target = working_tree_target(vcs, context)
        if target is None:
            return 1
    try:
        items = find(
            storage, app_name, ref, experiment_conf(vcs),
            top=args.top or DEFAULT_TOP, query=args.query, context=context,
            text_only=args.text_only, all_apps=args.all_apps,
            schema_of=conf_schema_of(getattr(vcs, "vmn_root_path", None)),
            target=target, include_archived=args.archived,
        )
    except QueryError as exc:
        VMN_LOGGER.error(f"Invalid --query: {exc}")
        return 1
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    print_items(items, app_name, as_json=args.json, with_app=args.all_apps)
    return 0


def _has_ref(args):
    return bool(args.version) or args.latest


def _ref(args):
    """The run ``-v``/``--latest`` names (``--latest`` wins), None for neither."""
    if args.latest:
        return "latest"
    return args.version[0] if args.version else None


def _check_flags(vcs, args, context):
    if args.top is not None and args.top < 1:
        return "--top must be at least 1"
    if args.text_only and context is None:
        return "--text-only needs --context or --context-file"
    if vcs is None and not _has_ref(args) and not args.text_only:
        return NEEDS_A_TREE
    return None


def working_tree_target(vcs, context):
    """The target of the uncommitted tree (no run is created), or None after
    logging why it could not be read."""
    try:
        captured, err = capture.capture_snapshot(vcs)
        if err is not None:
            return None
        row = {"code_verstr": captured.code_verstr, "base_version": captured.base_version,
               "branch": vcs.backend.logical_branch()}
        features = features_for_working_tree(vcs, captured)
    except Exception as exc:
        VMN_LOGGER.error(f"Could not read the working tree's changes: {exc}")
        VMN_LOGGER.debug("Working tree capture failed", exc_info=True)
        return None
    return {"row": row, "features": features or None, "text": context, "text_only": False}
