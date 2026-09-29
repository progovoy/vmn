"""``vmn-exp importance <app> --metric m``: which params drive a metric.

Scores every param over the runs ``list --query`` would show (archived ones
only with ``--archived``) — see :mod:`vmn_exp.core.importance` — and prints a
table, most important first, or the raw entries with ``--json``.
"""
from vmn_exp.cli.views import dumps
from vmn_exp.core.query import QueryError
from vmn_exp.sdk.reader import param_importance
from version_stamp.api import VMN_LOGGER

BAR_WIDTH = 20


def experiment_importance(storage, app_name, args):
    if not args.metric:
        VMN_LOGGER.error("importance needs --metric <name>")
        return 1
    try:
        entries = param_importance(
            app_name, args.metric, storage=storage, query=args.query,
            include_archived=args.archived,
        )
    except QueryError as exc:
        VMN_LOGGER.error(f"Invalid --query: {exc}")
        return 1
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    if args.json:
        print(dumps(entries))
    else:
        _print_table(entries)
    return 0


def _print_table(entries):
    width = max([len("param")] + [len(entry["param"]) for entry in entries])
    print(f"{'param':<{width}}  importance  {'':<{BAR_WIDTH}}  correlation  kind         n")
    for entry in entries:
        bar = "#" * round(entry["importance"] * BAR_WIDTH)
        corr = entry["correlation"]
        corr = "-" if corr is None else f"{corr:+.3f}"
        print(
            f"{entry['param']:<{width}}  {entry['importance']:>10.3f}  {bar:<{BAR_WIDTH}}"
            f"  {corr:>11}  {entry['kind']:<11}  {entry['n']}"
        )
