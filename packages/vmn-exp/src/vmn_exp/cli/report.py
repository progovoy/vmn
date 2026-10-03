"""``vmn-exp report list|show|export|put|delete`` (docs/plans/13-reports-comments.md §8.3).

Store-only and git-free, with the storage resolution of ``vmn-exp model``.
"""
import json
import os
import sys

from vmn_exp.cli import report_export
from vmn_exp.registry.cli import _get_storage
from vmn_exp.registry.cli_parser import _add_storage_args
from vmn_exp.reports import store


def add_report_parser(subparsers):
    preport = subparsers.add_parser("report", help="Reports: list, show, export, put, delete")
    preport.set_defaults(strict_version=False)
    sub = preport.add_subparsers(dest="action", metavar="action")
    sub.required = True
    plist = sub.add_parser("list", help="List reports")
    plist.add_argument("--archived", action="store_true", help="List archived reports instead")
    plist.add_argument("--json", action="store_true", help="Machine-readable output")
    pshow = sub.add_parser("show", help="Print a report's latest revision")
    pshow.add_argument("rid")
    pshow.add_argument("--json", action="store_true", help="Machine-readable output")
    pexport = sub.add_parser("export", help="Export a report as one self-contained HTML file")
    pexport.add_argument("rid")
    pexport.add_argument("--rev", type=int, default=None, help="Revision (default: the published one, else latest)")
    pexport.add_argument("-o", "--output", default="report.html", help="Output file (default report.html)")
    pexport.add_argument("--max-media-mb", type=float, default=20, help="Cap on inlined media (default 20)")
    pput = sub.add_parser("put", help="Save a markdown file as a report's next revision")
    pput.add_argument("rid", nargs="?", default=None)
    pput.add_argument("--new", action="store_true", help="Create a new report")
    pput.add_argument("-f", "--file", required=True, help="Markdown file")
    pput.add_argument("--title", default=None, help="Title of a --new report")
    pput.add_argument("-m", "--message", default="", help="Revision message")
    pdelete = sub.add_parser("delete", help="Delete a report, its revisions and comments")
    pdelete.add_argument("rid")
    for parser in (plist, pshow, pexport, pput, pdelete):
        _add_storage_args(parser)
    return preport


def _error(message):
    print(message, file=sys.stderr)
    return 1


def _cmd_list(storage, args):
    reports = [r for r in store.list_reports(storage) if bool(r.get("archived")) == args.archived]
    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "body"} for r in reports]))
        return 0
    for r in reports:
        print(f"{r['rid']}  v{r['rev']}  {r.get('title') or ''}")
    return 0


def _cmd_show(storage, args):
    report = store.get(storage, args.rid)
    if report is None:
        return _error(f"Report {args.rid!r} not found")
    if args.json:
        print(json.dumps(report))
    else:
        print(f"{report.get('title') or ''}  ({report['rid']} v{report['rev']})\n")
        print(report["body"])
    return 0


def _export_rev(report, args):
    if args.rev is not None:
        return args.rev
    return report.get("published_rev") or report["rev"]


def _cmd_export(storage, args):
    report = store.get(storage, args.rid)
    if report is None:
        return _error(f"Report {args.rid!r} not found")
    rev = _export_rev(report, args)
    revision = store.revision(storage, args.rid, rev)
    if revision is None:
        return _error(f"Report {args.rid!r} has no revision {rev}")
    panels = report_export.panel_payloads(storage, args.rid, rev)
    if not panels:
        print(f"Revision {rev} is not published: panels will show no data", file=sys.stderr)
    media, skipped = report_export.collect_media(storage, panels, int(args.max_media_mb * 1024 * 1024))
    for uri in skipped:
        print(f"Not inlined (missing or over --max-media-mb): {uri}", file=sys.stderr)
    data = {"title": report.get("title") or args.rid, "rev": rev, "body": revision["body"],
            "panels": panels, "media": media}
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report_export.build_html(data, *report_export.load_bundle()))
    print(args.output)
    return 0


def _title_of(body, path):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return os.path.splitext(os.path.basename(path))[0]


def _cmd_put(storage, args):
    if args.new == bool(args.rid):
        return _error("Give a report id or --new (not both)")
    with open(args.file, encoding="utf-8") as f:
        body = f.read()
    if args.new:
        rid = store.create(storage, args.title or _title_of(body, args.file), body)
        print(f"{rid}  v1")
        return 0
    if store.get(storage, args.rid) is None:
        return _error(f"Report {args.rid!r} not found")
    result = store.save(storage, args.rid, store.latest_rev(storage, args.rid), body, args.message)
    if isinstance(result, store.Conflict):
        return _error(f"Revision {result.rev} was saved concurrently; retry")
    print(f"{args.rid}  v{result}")
    return 0


def _cmd_delete(storage, args):
    if store.get(storage, args.rid) is None:
        return _error(f"Report {args.rid!r} not found")
    store.delete(storage, args.rid)
    return 0


_DISPATCH = {"list": _cmd_list, "show": _cmd_show, "export": _cmd_export,
             "put": _cmd_put, "delete": _cmd_delete}


def report_run_without_repo(args):
    return _DISPATCH[args.action](_get_storage(args), args)
