"""Flags that pick runs or shape a read: -v, --latest, --last, --query,
--archived, --json."""


def add_version(parser):
    parser.add_argument("-v", "--version", action="append", default=None,
                        help="Version string(s). Repeatable for compare; prune deletes "
                             "exactly the named run(s) instead of applying "
                             "--keep/--older-than. similar: without -v/--latest it "
                             "compares the current working tree, to ask before you "
                             "submit: the one action whose missing ref means the working "
                             "tree (show/restore/export take the latest run)")


def add_latest(parser):
    parser.add_argument("--latest", action="store_true", default=False,
                        help="Use the most recent experiment (for show/compare/restore/"
                             "export/similar)")


def add_last(parser):
    parser.add_argument("--last", type=int, default=None,
                        help="Use the N most recent experiments (for list/compare)")


def add_query(parser):
    parser.add_argument("--query", default=None,
                        help="list/importance/similar: filter rows by query "
                             "(e.g. 'metrics.loss < 0.5'); "
                             "prune: select candidates by query (dry-run unless --yes/-y); "
                             "archive/unarchive: act on every run the query selects")


def add_archived(parser):
    parser.add_argument("--archived", action="store_true", default=False,
                        help="list/importance/similar: include archived runs")


def add_json(parser):
    parser.add_argument("--json", action="store_true", default=False,
                        help="list, show, compare, importance, lineage, push, rerun, "
                             "similar: print machine-readable JSON")
