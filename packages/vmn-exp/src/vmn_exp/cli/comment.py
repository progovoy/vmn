"""``vmn-exp comment <app> -v <ref> "text"`` and ``vmn-exp comments <app> -v <ref>``
(docs/plans/13-reports-comments.md §8.3). Git-free, like ``vmn-exp model``."""
import sys

from vmn_exp.core.refs import resolve_experiment
from vmn_exp.registry.cli import _get_storage
from vmn_exp.registry.cli_parser import _add_storage_args
from vmn_exp.reports import comments


def _add_target_args(parser):
    parser.add_argument("name", help="App name")
    parser.add_argument("-v", "--version", dest="version_ref", required=True,
                        help="Run ref (verstr, @N, prefix)")
    _add_storage_args(parser)


def add_comment_parser(subparsers):
    pcomment = subparsers.add_parser("comment", help="Comment on a run")
    pcomment.set_defaults(strict_version=False)
    _add_target_args(pcomment)
    pcomment.add_argument("text", help="Comment text")
    return pcomment


def add_comments_parser(subparsers):
    pcomments = subparsers.add_parser("comments", help="Print a run's comment thread")
    pcomments.set_defaults(strict_version=False)
    _add_target_args(pcomments)
    return pcomments


def _target(storage, args):
    verstr, err = resolve_experiment(storage, args.name, args.version_ref)
    if err or not storage.exists(args.name, verstr):
        print(err or f"Run {args.version_ref!r} of {args.name!r} not found", file=sys.stderr)
        return None
    return ("run", args.name, verstr)


def comment_run_without_repo(args):
    storage = _get_storage(args)
    target = _target(storage, args)
    if target is None:
        return 1
    print(comments.add(storage, target, args.text))
    return 0


def comments_run_without_repo(args):
    storage = _get_storage(args)
    target = _target(storage, args)
    if target is None:
        return 1
    for c in comments.thread(storage, target):
        author = (c.get("author") or {})
        who = author.get("name") or author.get("git_user_email") or author.get("os_user") or "?"
        text = "[deleted]" if c["deleted"] else c["text"]
        reply = f" (reply to {c['reply_to']})" if c.get("reply_to") else ""
        print(f"{c['id']}  {c['ts']}  {who}{reply}: {text}")
    return 0
