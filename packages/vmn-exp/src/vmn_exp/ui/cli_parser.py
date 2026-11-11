"""The `vmn-exp ui` parser: serving by default, maintenance verbs as subcommands.

Each verb takes only its own flags. The verbs still hand the handlers the
``args.ui_args`` list they always read (``["cache", "rebuild"]``,
``["backup", path]``, ``["diag"]``, ``["onboarding"]``).
"""
import argparse

from vmn_exp.cli.views import positive_int


class _VerbArg(argparse.Action):
    """A verb's optional positional, stored as ``ui_args = [verb, value]``;
    a missing one stores ``[verb]`` so the handler's usage error still fires."""

    def __init__(self, option_strings, dest, verb, **kwargs):
        kwargs.pop("default", None)  # the verb parser's argument_default
        super().__init__(option_strings, dest, nargs="?", default=None, **kwargs)
        self.verb = verb

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.ui_args = [self.verb] + ([values] if values is not None else [])


def add_ui_parser(subparsers):
    pui = subparsers.add_parser(
        "ui", help="Serve the vmn web UI (experiments, stamp tree, actions)")
    pui.set_defaults(ui_args=[])
    _add_source_flags(pui)
    _add_serve_flags(pui)
    verbs = pui.add_subparsers(
        title="maintenance", metavar="{cache,onboarding,backup,diag}",
        description="'vmn-exp ui <verb> --help' lists that verb's flags")
    _add_cache(verbs)
    _add_onboarding(verbs)
    _add_backup(verbs)
    _add_diag(verbs)
    return pui


def _verb(verbs, name, help_text):
    """A verb parser whose flags default to absent, so a source flag given
    before the verb is never overwritten by the verb's default."""
    parser = verbs.add_parser(name, help=help_text, argument_default=argparse.SUPPRESS)
    _add_source_flags(parser)
    return parser


def _add_source_flags(parser):
    parser.add_argument("--config",
                        help="Server config file (server.yml); flags override its values")
    parser.add_argument("--db",
                        help="Control-plane DB DSN (sqlite:///path or postgresql://...; or "
                             "VMN_UI_DB). Keeps the workspace registry in the DB; "
                             "Postgres also holds the shared cache for replicas")
    parser.add_argument("--token",
                        help="Bearer token required for API access (or VMN_UI_TOKEN env)")
    parser.add_argument("--data-dir",
                        help="Server data dir for the workspace registry and index "
                             "(default: ~/.vmn-ui)")
    parser.add_argument("--repo", action="append",
                        help="Attach a local checkout as a workspace (repeatable)")
    parser.add_argument("--store",
                        help="Read-only experiment store URI (s3://, gs://, az://, file://)")


def _add_serve_flags(pui):
    pui.add_argument("--host", default="127.0.0.1", help="Bind address")
    pui.add_argument("--port", type=int, default=8265, help="Port (default 8265)")
    pui.add_argument("--allowed-host", action="append", default=None,
                     help="Extra hostname clients may reach the server by (repeatable).")
    pui.add_argument("--read-only", action="store_true", default=False,
                     help="Disable all mutation endpoints")
    pui.add_argument("--no-browser", action="store_true", default=False,
                     help="Do not open a browser on start")
    pui.add_argument("--no-index", action="store_true", default=False,
                     help="Keep no on-disk read cache (the index lives in memory only)")
    pui.add_argument("--keep-warm", dest="keep_warm", action="store_const", const=True,
                     default=None,
                     help="Keep refreshing every index once loaded, with nobody watching "
                          "(default: on for store workspaces, off for checkouts; or "
                          "server.keep_warm)")
    pui.add_argument("--no-keep-warm", dest="keep_warm", action="store_const", const=False,
                     help="Let an index nobody asked for in 60 s stop refreshing")
    pui.add_argument("--metrics-ended-hours", type=positive_int, default=None, metavar="H",
                     help="Keep an ended outer run on /metrics for H hours (default 24; "
                          "or server.metrics_ended_hours)")
    pui.add_argument("--diag-every", type=float, default=None, metavar="SEC",
                     help="Write a diagnostic dump to <data-dir>/diag/ every SEC seconds "
                          "(keeps the last 20; SIGUSR1 writes one on demand)")


def _add_cache(verbs):
    parser = _verb(verbs, "cache", "'cache resync' re-checks every record of the cache, "
                                   "'cache rebuild' rebuilds it")
    parser.add_argument("cache_action", action=_VerbArg, verb="cache",
                        metavar="resync|rebuild")
    parser.add_argument("--workspace", default=None,
                        help="the workspace to resync (default: every one)")


def _add_onboarding(verbs):
    parser = _verb(verbs, "onboarding", "print the BYO-bucket IAM policy for --store")
    parser.set_defaults(ui_args=["onboarding"])
    parser.add_argument("--edits", action="store_true", default=False,
                        help="also grant the puts server-side edits need")
    parser.add_argument("--format", dest="onboarding_format", default="json",
                        choices=("json", "cloudformation", "terraform"),
                        help="output format (default: json)")
    parser.add_argument("--account-id", default=None,
                        help="the AWS account the role trusts")
    parser.add_argument("--external-id", default=None,
                        help="the org's AssumeRole external id")
    parser.add_argument("--origin", action="append", default=None,
                        help="a browser origin allowed by bucket CORS (repeatable)")


def _add_backup(verbs):
    parser = _verb(verbs, "backup", "copy the SQLite control plane to <path> "
                                    "(Postgres: print the pg_dump command)")
    parser.add_argument("backup_path", action=_VerbArg, verb="backup", metavar="path")


def _add_diag(verbs):
    parser = _verb(verbs, "diag", "take a diagnostic dump of a running server, "
                                  "or summarize one")
    parser.set_defaults(ui_args=["diag"])
    parser.add_argument("--url", dest="diag_url", default=None,
                        help="the server's base URL (e.g. http://host:8265)")
    parser.add_argument("--pid", dest="diag_pid", type=int, default=None,
                        help="signal this vmn-exp ui process (SIGUSR1) to write a dump "
                             "into <data-dir>/diag/")
    parser.add_argument("--wait", dest="diag_wait", type=float, default=30,
                        help="--pid: seconds to wait for the dump (default: 30)")
    parser.add_argument("--summarize", dest="diag_summarize", default=None, metavar="FILE",
                        help="print the summary of an existing dump")
    parser.add_argument("-o", "--output", dest="diag_output", default=None, metavar="FILE",
                        help="where to write the dump (default: "
                             "vmn-exp-diag-<ts>.json; --pid: the server's file)")
