"""``vmn-exp compare``: the comparison of runs as a payload (``--json``) and
the metric and param tables printed from it."""
from vmn_exp.cli.views import (
    format_number,
    policy_conflict,
    shown_policies,
    split_params,
    with_policy,
)
from vmn_exp.core.fold import fold_log, fold_metrics, fold_values, logged_params
from vmn_exp.core.metric_summary import SchemaPolicies


def _compare_run(meta, log, schema, policies):
    """A run's entry: its logged metrics, the policy behind each value but
    ``last`` and its params."""
    fold = fold_log(log)
    metrics, _, overrides = fold_metrics(fold, schema)
    logged, params = split_params(metrics, fold_values(fold, "params"), logged_params(fold))
    shown = shown_policies(logged, overrides, policies)
    return {"verstr": meta["verstr"], "metrics": logged, "params": params,
            "metric_policy": {k: p for k, p in shown.items() if p}}


def _metric_order(schema, keys):
    """Schema-declared metrics first, then the rest alphabetically."""
    declared = [k for k in schema or {} if k in keys]
    return declared + sorted(keys - set(declared))


def _conflicts(runs, keys):
    """``{metric: "summaries differ: ..."}`` where the runs' policies differ."""
    found = {}
    for key in keys:
        text = policy_conflict(
            r["metric_policy"].get(key) for r in runs if r["metrics"].get(key) is not None)
        if text:
            found[key] = text
    return found


def compare_payload(experiments, schema):
    """The ``compare --json`` object of *experiments* (``(meta, patches, log)``
    bundles) under the app's metrics *schema*."""
    policies = SchemaPolicies(schema)
    runs = [_compare_run(meta, log, schema, policies) for meta, _, log in experiments]
    metrics = _metric_order(schema, set().union(*(r["metrics"] for r in runs)))
    return {"runs": runs, "metrics": metrics,
            "params": sorted(set().union(*(r["params"] for r in runs))),
            "conflicts": _conflicts(runs, metrics)}


def _table(label, runs, keys, cell, note=lambda key: None):
    """The lines of a compare table: a *label* column of *keys*, one column per
    run, *cell(run, key)* its values and *note(key)* an optional suffix."""
    headers = [label] + [r["verstr"][-20:] for r in runs]
    col_widths = [max(len(h), 12) for h in headers]
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    lines = [header_line, "-" * len(header_line)]
    for key in keys:
        row = [key] + [cell(r, key) for r in runs]
        line = "  ".join(str(v).ljust(w) for v, w in zip(row, col_widths))
        suffix = note(key)
        lines.append(f"{line}  {suffix}" if suffix else line)
    return lines


def _cell(values, policies, key):
    """A compare table's cell: ``0.2 (min)``, ``-`` without a value."""
    if values.get(key) is None:
        return "-"
    return with_policy(format_number(values[key]), policies.get(key))


def _diff_hint(runs, app_name):
    """The ``vmn-exp diff`` hint's lines: one for two runs, else none."""
    if len(runs) != 2:
        return []
    v1, v2 = (r["verstr"] for r in runs)
    return [f"Run 'vmn-exp diff {app_name} -v {v1} -v {v2}' for a code diff."]


def compare_text(payload, app_name):
    """The metric table, then the param table, of a :func:`compare_payload`,
    and the ``vmn-exp diff`` hint for two runs."""
    runs, blocks = payload["runs"], []
    if payload["metrics"]:
        blocks.append(_table(
            "metric", runs, payload["metrics"],
            lambda r, key: _cell(r["metrics"], r["metric_policy"], key),
            payload["conflicts"].get))
    if payload["params"]:
        blocks.append(_table(
            "param", runs, payload["params"], lambda r, key: _cell(r["params"], {}, key)))
    blocks.append(_diff_hint(runs, app_name))
    return "\n\n".join("\n".join(block) for block in blocks if block)
