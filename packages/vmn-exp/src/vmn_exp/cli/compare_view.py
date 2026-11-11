"""``vmn-exp compare`` and ``diff``: the comparison of runs as a payload
(``--json``), the metric and param tables printed from it, and the code diff.

``_resolve_experiment_bundles`` and ``_resolve_experiment_version`` are looked
up on :mod:`vmn_exp.cli.experiment` at call time, so a test's patch there
still reaches these commands (plan 44 G15). Their text goes to the given
console (plan 44 G16)."""
from vmn_exp.cli.provenance import print_provenance_diff_section, refuse_no_code
from vmn_exp.cli.views import (
    dumps,
    format_number,
    metrics_schema,
    policy_conflict,
    shown_policies,
    split_params,
    with_policy,
)
from vmn_exp.core.fold import fold_log, fold_metrics, fold_values, logged_params
from vmn_exp.core.log import effective_params, load_log
from vmn_exp.core.metric_summary import SchemaPolicies
from vmn_exp.core.refs import placement_snapshot, recent_verstrs
from vmn_exp.snapshot import _diff_real_tree, _diff_with_external_tool, get_git_difftool
from version_stamp.api import VMN_LOGGER, measure_runtime_decorator


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


def _load_metadata(storage, app_name, verstr):
    """An experiment's metadata alone — no patches or untracked tarball."""
    return storage.load_metadata(app_name, verstr)


def _load_experiment_bundle(storage, vcs, verstr, app_name=None, light=False):
    """Load (meta, patches, log) for an experiment, or None (logging) on error.

    *light* skips the patches (``None`` in their slot): what compare needs.
    """
    from vmn_exp.cli import experiment as _exp

    app_name = app_name or (_exp._app_name(vcs))
    if light:
        meta, patches = _load_metadata(storage, app_name, verstr), None
    else:
        meta, patches = storage.load(app_name, verstr)
    if meta is None:
        VMN_LOGGER.error(f"Experiment {verstr} not found")
        return None
    return meta, patches, load_log(storage, app_name, verstr)


def _resolve_experiment_bundles(
    storage, vcs, versions, count, cap=None, app_name=None, light=False
):
    """Resolve (meta, patches, log) bundles for compare/diff.

    Uses the given ``-v`` versions (each resolved), or the ``count`` most recent
    when none are given; ``cap`` limits how many are taken. Returns the list, or
    None (logging) on error — at least two experiments are required. *light*
    loads no patches.
    """
    from vmn_exp.cli import experiment as _exp

    app_name = app_name or (_exp._app_name(vcs))

    if len(versions) == 1:
        VMN_LOGGER.error(
            "Need at least 2 experiments — pass -v <a> -v <b> or none for the latest"
        )
        return None

    if versions:
        verstrs = []
        snapshot = placement_snapshot(storage, app_name)
        for v in versions[:cap] if cap else versions:
            resolved, err = _exp._resolve_experiment_version(
                storage, vcs, _exp._VersionStub(version=[v]), snapshot=snapshot
            )
            if err:
                VMN_LOGGER.error(err)
                return None
            verstrs.append(resolved)
    else:
        if count < 2:
            VMN_LOGGER.error(f"Need at least 2 experiments, got {count}")
            return None
        verstrs = recent_verstrs(storage, app_name, count)
        if len(verstrs) < 2:
            VMN_LOGGER.error("Need at least 2 experiments")
            return None

    bundles = []
    for verstr in verstrs:
        bundle = _load_experiment_bundle(
            storage, vcs, verstr, app_name=app_name, light=light
        )
        if bundle is None:
            return None
        bundles.append(bundle)
    return bundles


def _metrics_with_policies(log, schema, policies):
    """A run's summary metrics and the policy behind each value (None: ``last``)."""
    metrics, _, overrides = fold_metrics(fold_log(log), schema)
    return metrics, shown_policies(metrics, overrides, policies)


@measure_runtime_decorator
def experiment_compare(vcs, params, storage, args, console):
    from vmn_exp.cli import experiment as _exp

    versions = getattr(args, "version", None) or []
    last = getattr(args, "last", None) or getattr(args, "top", None)
    app_name = _exp._app_name(vcs, args)

    experiments = _exp._resolve_experiment_bundles(
        storage, vcs, versions, count=last or 2, app_name=app_name, light=True
    )
    if experiments is None:
        return 1

    payload = compare_payload(experiments, metrics_schema(vcs, storage, app_name))
    text = dumps(payload) if args.json else compare_text(payload, app_name)
    if text:
        console.out(text)
    return 0


def _delta_text(key, a, b, p1, p2):
    """``loss 0.2 (min) -> 0.9 (summaries differ: min vs last)``: each value
    naming its policy (None: ``last``), the second side the conflict."""
    if a is not None and b is not None:
        p2 = policy_conflict((p1, p2)) or p2
    return f"{key} {with_policy(format_number(a), p1)} -> {with_policy(format_number(b), p2)}"


def _print_delta_line(out, label, d1, d2, policies=({}, {})):
    p1, p2 = policies
    parts = []
    for k in sorted(set(d1) | set(d2)):
        a, b = d1.get(k), d2.get(k)
        if a != b:
            parts.append(_delta_text(k, a, b, p1.get(k), p2.get(k)))
    if parts:
        out(f"{label}: " + "   ".join(parts))


@measure_runtime_decorator
def experiment_diff(vcs, params, storage, args, console):
    """Show a real code diff between two experiments, with a params/metrics delta."""
    from vmn_exp.cli import experiment as _exp

    versions = getattr(args, "version", None) or []
    exps = _exp._resolve_experiment_bundles(storage, vcs, versions, count=2, cap=2)
    if exps is None:
        return 1
    (meta1, patches1, log1), (meta2, patches2, log2) = exps
    v1, v2 = meta1["verstr"], meta2["verstr"]
    app_name = _exp._app_name(vcs, args)

    out = console.out
    out(f"Comparing {v1} -> {v2}\n")
    _print_delta_line(out, "params", effective_params(log1), effective_params(log2))
    schema = metrics_schema(vcs, storage, app_name)
    policies = SchemaPolicies(schema)
    (m1, shown1), (m2, shown2) = (_metrics_with_policies(log, schema, policies) for log in (log1, log2))
    _print_delta_line(out, "metrics", m1, m2, (shown1, shown2))

    print_provenance_diff_section(storage, app_name, v1, meta1, v2, meta2, out)
    out("")

    # Refuse code diff for runs with no code snapshot (e.g. MLflow imports)
    for meta in (meta1, meta2):
        rc = refuse_no_code(meta, action="diff")
        if rc is not None:
            return rc

    tool = getattr(args, "tool", None) or get_git_difftool(vcs)
    if tool:
        return _diff_with_external_tool(
            tool, vcs, v1, meta1, patches1, v2, meta2, patches2
        )
    return _diff_real_tree(vcs, v1, meta1, patches1, v2, meta2, patches2)
