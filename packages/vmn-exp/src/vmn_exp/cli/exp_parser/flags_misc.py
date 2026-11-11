"""The flags one or two actions own that need no file of their own."""
from vmn_exp.cli import views


def add_tag(parser):
    parser.add_argument("--remove", action="append", default=None,
                        help="tag: remove this tag key (repeatable)")


def add_importance(parser):
    parser.add_argument("--metric", default=None,
                        help="importance: the metric whose driving params to rank")


def add_diff(parser):
    parser.add_argument("--tool", default=None,
                        help="External diff tool for compare. Falls back to git config "
                             "diff.tool")


def add_output(parser):
    parser.add_argument("-o", "--output", default=None, help="Output path for export")


def add_dry_run(parser):
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False,
                        help="prune: print what would be deleted, delete nothing; "
                             "archive/unarchive --query: print what would change, write "
                             "nothing; rerun: print the plan, create nothing; "
                             "push: print what would be pushed, write nothing remote; "
                             "similar-backfill/backfill-children: print what would be "
                             "backfilled, write nothing")


def add_push(parser):
    parser.add_argument("--adopt", action="store_true", default=False,
                        help="push: make this checkout the owner of the streams its runs "
                             "inherited from a copied/moved checkout, then push them; only "
                             "when that checkout is gone or will never write again")


def add_force(parser):
    parser.add_argument("--force", action="store_true", default=False,
                        help="prune: also delete runs that are still running; restore: "
                             "even if untracked files over the snapshot size caps would "
                             "be deleted without being saved; add --finish: even a run "
                             "that heartbeats elsewhere or has finished (--force-live: "
                             "only the first)")


def add_show(parser):
    parser.add_argument("--full-log", action="store_true", default=False,
                        help="show: print every log entry (default: the last 50)")
    parser.add_argument("--patch", action="store_true", default=False,
                        help="show: also print the run's own patches (working tree, local "
                             "commits, deps; never untracked files)")
    parser.add_argument("--max-bytes", type=views.positive_max_bytes,
                        default=views.PATCH_MAX_BYTES, metavar="N",
                        help="show --patch: print at most N bytes of patch text "
                             f"(default: {views.PATCH_MAX_BYTES})")


def add_watch(parser):
    parser.add_argument("--interval", type=float, default=None,
                        help="watch: re-check every N seconds (default: check once, for "
                             "cron)")
    parser.add_argument("--within", default=None,
                        help="watch: only alert transitions newer than this (e.g. 6h, 1d; "
                             "default 1d)")
    parser.add_argument("--compact", action="store_true", default=False,
                        help="watch: also compact the metrics of failed/stuck runs")


def add_export_metrics(parser):
    parser.add_argument("--keys", nargs="+", default=None,
                        help="export-metrics: only these metric keys")
    parser.add_argument("--format", dest="metrics_format", default=None,
                        choices=("parquet", "csv"),
                        help="export-metrics: output format (default: from -o, else "
                             "parquet)")


def add_compact(parser):
    parser.add_argument("--all-finished", action="store_true", default=False,
                        help="compact: every succeeded or failed run")


def add_all_apps(parser):
    parser.add_argument("--all-apps", action="store_true", default=False,
                        help="similar/similar-backfill: every app of the store, not just "
                             "<name>")


def add_lineage(parser):
    parser.add_argument("--depth", type=int, default=1,
                        help="lineage: follow links this many hops (default: 1)")


def add_rewind(parser):
    parser.add_argument("--step", type=int, default=None, metavar="N",
                        help="rewind: hide the run's history past step N")
