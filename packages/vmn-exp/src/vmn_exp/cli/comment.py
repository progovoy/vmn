"""``vmn-exp comment <app> -v <ref> "text"`` and ``vmn-exp comments <app> -v <ref>``
(docs/plans/13-reports-comments.md §8.3). Git-free, like ``vmn-exp model``."""
import sys

from vmn_exp.cli.views import dumps
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.cli.model_cmd import _get_storage
from vmn_exp.cli.storage_flags import _add_storage_args
from vmn_exp.reports import comments


def _add_target_args(parser):
    parser.add_argument("name", help="App name")
    parser.add_argument("-v", "--version", dest="version_ref", required=True,
                        help="Run ref (verstr, @N, prefix)")
    _add_storage_args(parser)
    parser.add_argument("--json", action="store_true", default=False,
                        help="print machine-readable JSON")


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


def _stored(comment):
    """A thread entry as stored, without the text of a deleted one."""
    return {k: v for k, v in comment.items() if not (k == "text" and comment["deleted"])}


def comment_run_without_repo(args, io, checkout):
    return comment_run(_get_storage(args, io.clock, io.env, checkout), args, io.random, io.env, io.host)


def comment_run(storage, args, random, env, host):
    target = _target(storage, args)
    if target is None:
        return 1
    comment_id = comments.add(storage, target, args.text, random=random, env=env, host=host)
    print(dumps({"id": comment_id}) if args.json else comment_id)
    return 0


def comments_run_without_repo(args, io, checkout):
    return comments_run(_get_storage(args, io.clock, io.env, checkout), args)


def _thread_line(c):
    author = (c.get("author") or {})
    who = author.get("name") or author.get("git_user_email") or author.get("os_user") or "?"
    text = "[deleted]" if c["deleted"] else c["text"]
    reply = f" (reply to {c['reply_to']})" if c.get("reply_to") else ""
    return f"{c['id']}  {c['ts']}  {who}{reply}: {text}"


def comments_run(storage, args):
    target = _target(storage, args)
    if target is None:
        return 1
    thread = comments.thread(storage, target)
    lines = [dumps([_stored(c) for c in thread])] if args.json else map(_thread_line, thread)
    for line in lines:
        print(line)
    return 0
