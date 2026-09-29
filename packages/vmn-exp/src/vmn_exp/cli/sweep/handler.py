"""``vmn-exp sweep create`` and ``status``, and the command's dispatch."""
from vmn_exp.cli.experiment import (
    _experiment_create_core,
    _resolve_parent,
    auto_init,
    experiment_storage_params,
)
from vmn_exp.cli.views import dumps
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.storage_resolve import _get_experiment_storage
from vmn_exp.core.sweep.claims import claimed_trials
from vmn_exp.core.sweep.spec import SpecError, load_spec, parse_spec
from vmn_exp.core.sweep.summary import summarize, trial_rows
from vmn_exp.core.writer import flush_log
from version_stamp.api import VMN_LOGGER


def handle_sweep(vmn_ctx):
    vcs, args = vmn_ctx.vcs, vmn_ctx.args
    params = experiment_storage_params(vcs, args)
    if args.action == "create":
        err = auto_init(vmn_ctx)
        if err:
            return err
    storage = _get_experiment_storage(vcs, params)
    try:
        if args.action == "create":
            return sweep_create(vcs, storage, args)
        sweep, spec = resolve_sweep(storage, vcs.name, args.ref)
        if args.action == "status":
            return sweep_status(storage, vcs.name, sweep, spec, args)
        from vmn_exp.cli.sweep.agent import run_agent

        return run_agent(vcs, storage, args, sweep, spec, getattr(vmn_ctx, "repo_lock", None))
    except SpecError as exc:
        VMN_LOGGER.error(f"Sweep: {exc}")
        return 1


def sweep_create(vcs, storage, args):
    """The sweep's outer run, its normalized spec in the metadata."""
    if not args.file:
        raise SpecError("sweep create needs the spec: -f sweep.yml")
    try:
        spec = load_spec(args.file)
    except OSError as exc:
        raise SpecError(f"cannot read {args.file}: {exc}")
    parent, err = _resolve_parent(storage, vcs.name, args)
    if err is not None:
        return err
    verstr, err = _experiment_create_core(
        vcs, storage, note=args.note, name=args.run_name, parent=parent,
        extra_create_data={"tags": {"sweep": spec["method"]}},
        capture_env=getattr(args, "capture_env", None),
    )
    if err is not None:
        return err
    storage.update_metadata(vcs.name, verstr, {"sweep": spec})
    flush_log(storage, vcs.name, verstr)
    print(verstr)
    return 0


def resolve_sweep(storage, app_name, ref):
    """``(sweep verstr, spec)`` for *ref*; SpecError when it is no sweep."""
    if not ref:
        raise SpecError("name the sweep: vmn-exp sweep <action> <app> <sweep-ref>")
    verstr, err = resolve_experiment(storage, app_name, ref)
    if err:
        raise SpecError(err)
    meta = storage.load_metadata(app_name, verstr) or {}
    if not meta.get("sweep"):
        raise SpecError(f"{verstr} is not a sweep (create one with vmn-exp sweep create)")
    return verstr, parse_spec(meta["sweep"])


def sweep_status(storage, app_name, sweep, spec, args):
    summary = summarize(spec, trial_rows(storage, app_name, sweep, spec),
                        claimed_trials(storage, app_name, sweep))
    summary["sweep"] = sweep
    if args.json:
        print(dumps(summary))
    else:
        print(format_status(summary))
    return 0


def format_status(summary):
    metric = summary["metric"]
    cap = summary["run_cap"]
    lines = [
        f"sweep {summary['sweep']} ({summary['method']}, {metric['name']} "
        f"{metric['goal']}): {summary['trials']} trial(s)"
        + (f" of {cap}" if cap else ""),
        "  " + "  ".join(f"{status} {n}" for status, n in sorted(summary["counts"].items()))
        + f"  stopped_early {summary['stopped_early']}  unstarted {summary['unstarted']}",
    ]
    best = summary["best"]
    if best:
        params = ", ".join(f"{k}={v}" for k, v in sorted(best["params"].items()))
        lines.append(f"  best: trial {best['trial']} {best['verstr']} "
                     f"{metric['name']}={best['value']}  ({params})")
    return "\n".join(lines)
