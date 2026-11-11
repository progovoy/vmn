"""``vmn-exp list``: its rows, their layout (plan 39 B3) and their text.

The sort warning goes through :mod:`vmn_exp.cli.experiment`'s ``VMN_LOGGER``
at call time, so a test's patch there still reaches it (plan 44 G15).
Its text goes to the given console (plan 44 G16)."""
from types import SimpleNamespace

import vmn_exp.core.index_list as index_list
from vmn_exp.cli.list_hints import print_query_hints
from vmn_exp.cli.views import dumps, format_number, metrics_schema, shown_policies, with_policy
from vmn_exp.core.field_sort import field_sort
from vmn_exp.core.load_progress import incomplete_text
from vmn_exp.core.log import DATE_SORTS, IDX_SORT, filter_archived, sort_by_metric
from vmn_exp.core.metric_schema import effective_schema
from vmn_exp.core.metric_summary import SchemaPolicies
from vmn_exp.core.query import QueryError
from vmn_exp.core.status import CREATED
from vmn_exp.core.tree import sweep_incomplete
from version_stamp.api import VMN_LOGGER, measure_runtime_decorator, relative_timestamp


def list_layout(rows):
    """``(indent, parent_label)`` per row. In storage order (ascending
    ``idx``) a row indents by its tree depth. In any other order indentation
    would say nothing, so rows are flat and a child names its parent:
    ``^[N]`` when the parent is listed, else ``^<parent verstr>``."""
    idxs = [row["idx"] for row in rows]
    if idxs == sorted(idxs):
        return [(row["meta"]["depth"], "") for row in rows]
    listed = {row["meta"]["verstr"]: row["idx"] for row in rows}
    return [(0, _parent_label(row["meta"].get("parent"), listed)) for row in rows]


def _parent_label(parent, listed):
    if not parent:
        return ""
    return f"^[{listed[parent]}]" if parent in listed else f"^{parent}"


def _status_token(node):
    """A run's own status, plus its subtree's when the two disagree, and how
    far an incomplete sweep got (``created (16/20 incomplete)``)."""
    status = node["status"]
    tree_status = node.get("tree_status")
    token = f"{status}/{tree_status}" if tree_status and tree_status != status else status
    if tree_status == CREATED and sweep_incomplete(node):
        token += f" ({node['sweep_trials']}/{node['sweep_planned']} incomplete)"
    return token + _lost_text(node)


def _lost_text(tree):
    """`` · 2 lost``: an outer run's lost runs (plan 34 §3), else empty."""
    lost = tree.get("lost_below")
    return f" · {lost} lost" if lost else ""


def _list_rows(index_rows, last, sort, schema):
    """Rows for ``list``: ``idx`` is the storage index ``@N`` resolves, fixed
    before ``--last``/sort/``--top`` touch the order. Sorting runs on the flat
    rows, where the date fields (``timestamp``, ``started_at``, ...) live."""
    from vmn_exp.cli import experiment as _exp

    shown = index_rows[-last:] if last else index_rows
    if sort and sort not in (*DATE_SORTS, IDX_SORT) and not field_sort(sort) and not any(
        sort in row["metrics"] for row in shown
    ):
        _exp.VMN_LOGGER.warning(f"Sort key '{sort}' not found in any experiment")
    return [
        {"idx": row["idx"], "meta": row, "metrics": row["metrics"]}
        for row in sort_by_metric(shown, schema, sort=sort)
    ]


def _metric_columns(schema, rows):
    """Schema-declared metrics first, then the rest alphabetically."""
    keys = set()
    for row in rows:
        keys.update(row["metrics"])
    columns = list(schema or {})
    return columns + sorted(k for k in keys if k not in columns)


def _format_list_row(row, node, columns, policies, indent, parent_label):
    meta, metrics = row["meta"], row["metrics"]
    note = meta.get("note") or meta.get("create_note") or ""
    shown = shown_policies(metrics, meta.get("metric_policy"), policies)
    went_back = meta.get("step_restarts") or {}
    metric_str = "  ".join(
        f"{k}={with_policy(format_number(metrics[k]), shown[k])}"
        + (" (steps went back)" if k in went_back else "")
        for k in columns
        if k in metrics
    )
    note_str = f" - {note}" if note else ""
    name_str = f" '{meta['name']}'" if meta.get("name") else ""
    archived_str = " [archived]" if meta.get("archived") else ""
    parent_str = f" {parent_label}" if parent_label else ""
    return (
        f"{'  ' * indent}[{row['idx']}] {meta['verstr']}{name_str}{archived_str}{parent_str}  "
        f"{_status_token(node)}  ({relative_timestamp(meta['timestamp'])})  "
        f"{metric_str}{note_str}"
    )


def _listed(storage, app_name, args, schema):
    """``(rows, declared schema, app has runs, loading)``: the annotated runs
    the query and archived filter keep, in storage order — from the persisted
    index (only ``--last``'s without a query), else from a snapshot, whose
    ``loading`` it is (None when whole or from the persisted rows)."""
    query, archived = getattr(args, "query", None), getattr(args, "archived", False)
    view = index_list.list_view(
        storage, app_name, query, archived, getattr(args, "last", None), schema
    )
    if view is not None:
        return (*view, None)
    matching, declared, any_runs, loading = index_list.snapshot_listing(
        storage, app_name, query, schema, with_create_note=True
    )
    return filter_archived(matching, archived), declared, any_runs, loading


@measure_runtime_decorator
def experiment_list(vcs, params, storage, args, console):
    from vmn_exp.cli import experiment as _exp

    app_name = _exp._app_name(vcs, args)
    schema = metrics_schema(vcs, storage, app_name)
    try:
        matching, declared, any_runs, loading = _listed(storage, app_name, args, schema)
    except QueryError as e:
        VMN_LOGGER.error(f"Invalid --query: {e}")
        return 1
    as_json = getattr(args, "json", False)
    if loading is not None:
        console.err(incomplete_text(loading))
    if not any_runs and not as_json:
        if loading is None:
            console.out(f"No experiments found for {app_name}")
        return 0

    rows = _list_rows(
        matching, getattr(args, "last", None), args.sort, effective_schema(schema, declared)
    )
    if args.top:
        rows = rows[: args.top]
    if not matching and getattr(args, "query", None):
        every = SimpleNamespace(archived=getattr(args, "archived", False))
        print_query_hints(
            args.query, lambda: _listed(storage, app_name, every, schema)[0], console.err
        )

    if as_json:
        console.out(dumps([row["meta"] for row in rows]))
        return 0

    columns, policies = _metric_columns(schema, rows), SchemaPolicies(schema)
    for row, (indent, parent_label) in zip(rows, list_layout(rows)):
        console.out(_format_list_row(row, row["meta"], columns, policies, indent, parent_label))
    return 0
