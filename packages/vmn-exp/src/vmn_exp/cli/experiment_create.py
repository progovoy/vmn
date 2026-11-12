"""``vmn-exp create`` and ``add``: record a run, and append to one.

The shared argument helpers live in :mod:`vmn_exp.cli.experiment` and are
looked up there at call time, so a test's patch there (for example of
``_resolve_experiment_version``) still reaches these commands (plan 44 G15)."""
import os

from vmn_exp.cli import fork
from vmn_exp.cli.define_metric_args import define_metric_entry
from vmn_exp.cli.finish_args import apply_finish, finish_flags_error
from vmn_exp.cli.intent_arg import append_intent, read_intent
from vmn_exp.cli.run import _parse_metrics
from vmn_exp.cli.snapshot_arg import from_snapshot_metadata
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.from_snapshot import (
    create_from_snapshot as _experiment_create_from_snapshot,
)
from vmn_exp.core.writer import (
    append_to_log,
    compute_artifact_info,
    create_log_entry,
    flush_log,
    get_writer_id,
    new_run_ids,
    save_artifact,
)
from vmn_exp.gitmode import capture
from vmn_exp.gitmode.checkout import record_run
from vmn_exp.gitmode.features import capture_features
from version_stamp.api import VMN_LOGGER, measure_runtime_decorator


@measure_runtime_decorator
def experiment_create(vcs, params, storage, args, repo_lock=None, *, clock, env, host):
    """Create a run; ``repo_lock`` is the per-repo lock the CLI entry point
    acquired, handed back once the run is written (see :func:`experiment_run`);
    the similar-runs hint runs on *clock*; the snapshot and parent default to
    *env*'s ``VMN_SNAPSHOT_METADATA`` and ``VMN_EXPERIMENT_ID``; the writer
    id, run suffix and author are *env*'s and *host*'s."""
    from vmn_exp.cli import experiment as _exp

    extra = {}
    if getattr(args, "file", None):
        extra.update(_exp._parse_notes_file(args.file))

    from_snapshot = from_snapshot_metadata(args, env)
    app_name = _exp._app_name(vcs, args)
    parent, err = _exp._resolve_parent(storage, app_name, args, env)
    if err is not None:
        return err
    source, err = fork.fork_source(storage, app_name, args)
    if err is not None:
        return err
    intent, err = read_intent(args)
    if err is not None:
        return err

    verstr, err = _experiment_create_core(
        vcs,
        storage,
        note=args.note,
        from_snapshot=from_snapshot,
        extra_create_data=extra or None,
        parent=parent,
        name=getattr(args, "run_name", None),
        capture_env=getattr(args, "capture_env", None),
        env=env,
        host=host,
    )
    if err is not None:
        return err
    writer = get_writer_id(env, host)
    fork.seed(storage, app_name, verstr, source, writer)
    if intent:
        append_intent(storage, app_name, verstr, intent, writer)

    if getattr(args, "metrics", None):
        append_to_log(
            storage,
            app_name,
            verstr,
            create_log_entry("metrics", values=_parse_metrics(args.metrics)),
            writer,
        )

    _exp._append_inputs(storage, app_name, verstr, getattr(args, "inputs", None), writer)

    # One-shot command: nothing else will flush this to the remote later.
    flush_log(storage, app_name, verstr, writer)

    # The run is written: the hint below only reads, so other vmn commands
    # need not wait for it.
    if repo_lock is not None:
        repo_lock.release()
    from vmn_exp.cli.similar_hint import print_hint

    print_hint(storage, app_name, verstr, args, experiment_conf(vcs), clock=clock, env=env)
    print(verstr)
    return 0


def _experiment_create_core(
    vcs,
    storage,
    note=None,
    from_snapshot=None,
    extra_create_data=None,
    parent=None,
    name=None,
    capture_env=None,
    python_exe=None,
    *,
    env,
    host,
):
    """Create the experiment record (snapshot + initial log entry) as the
    writer of *env* and *host* (its author, writer id and run suffix).

    Returns (verstr, error_code). error_code is None on success.
    When from_snapshot is set, reads identity from vmn_metadata.yml (no git needed).

    *capture_env* follows the same precedence as ``start_run(capture_env=...)``:
    ``None`` = check opt-out chain, ``True`` = force on, ``False`` = force off.
    *python_exe*, when given, is probed instead of the current interpreter.
    *env* is the Env the capture opt-out is read from and the capture records.
    """
    from vmn_exp.cli import experiment as _exp
    from vmn_exp.core.env import (
        capture_env_safe,
        should_capture,
    )

    exp_conf = experiment_conf(vcs)

    if from_snapshot:
        app_name = _exp._app_name(vcs)
        captured_env = capture_env_safe(env) if should_capture(capture_env, exp_conf, env=env) else None
        return _experiment_create_from_snapshot(
            storage,
            app_name,
            from_snapshot,
            note=note,
            extra_create_data=extra_create_data,
            parent=parent,
            name=name,
            env=captured_env,
            environ=env,
            host=host,
        )

    captured, err = capture.capture_snapshot(vcs)
    if err is not None:
        return None, err

    # Capture env before the record is created (env capture is read-only).
    captured_env = (
        capture_env_safe(env, python_exe) if should_capture(capture_env, exp_conf, env=env) else None
    )
    code = capture.ensure_code(storage, vcs, captured)
    verstr = record_run(
        vcs, storage, captured, code, note, extra_create_data, parent, name, env=captured_env,
        features=capture_features(vcs, captured, env, host),
        **new_run_ids(env, host),
    )
    return verstr, None


@measure_runtime_decorator
def experiment_add(vcs, params, storage, args, io):
    from vmn_exp.cli import experiment as _exp

    verstr, err = _exp._resolve_experiment_version(storage, vcs, args, default_latest=True)
    if err:
        VMN_LOGGER.error(err)
        return 1

    app_name = _exp._app_name(vcs, args)
    try:
        definition = define_metric_entry(args)
    except ValueError as e:
        VMN_LOGGER.error(str(e))
        return 1
    err = finish_flags_error(args)
    if err:
        VMN_LOGGER.error(err)
        return 1
    intent, err = read_intent(args)
    if err is not None:
        return err
    writer = get_writer_id(io.env, io.host)
    if definition:
        append_to_log(storage, app_name, verstr, definition, writer)
        VMN_LOGGER.info(f"Defined metric {definition['name']} for {verstr}")

    if args.metrics:
        entry = create_log_entry("metrics", values=_parse_metrics(args.metrics))
        append_to_log(storage, app_name, verstr, entry, writer)
        VMN_LOGGER.info(f"Added metrics to {verstr}")

    if args.note:
        entry = create_log_entry("note", text=args.note)
        append_to_log(storage, app_name, verstr, entry, writer)
        VMN_LOGGER.info(f"Added note to {verstr}")

    if args.attach:
        if not os.path.isfile(args.attach):
            VMN_LOGGER.error(f"Artifact file not found: {args.attach}")
            return 1
        info = compute_artifact_info(args.attach)
        save_artifact(storage, app_name, verstr, args.attach)
        entry = create_log_entry("artifact", **info)
        append_to_log(storage, app_name, verstr, entry, writer)
        VMN_LOGGER.info(f"Attached {info['path']} to {verstr}")

    if args.file:
        notes_data = _exp._parse_notes_file(args.file)
        entry = create_log_entry("structured", **notes_data)
        append_to_log(storage, app_name, verstr, entry, writer)
        VMN_LOGGER.info(f"Added structured entry to {verstr}")

    _exp._append_inputs(storage, app_name, verstr, getattr(args, "inputs", None), writer)

    if intent:
        append_intent(storage, app_name, verstr, intent, writer)
        VMN_LOGGER.info(f"Added intent to {verstr}")

    # One-shot command: nothing else will flush this to the remote later.
    flush_log(storage, app_name, verstr, writer)

    return apply_finish(storage, app_name, verstr, args, io)
