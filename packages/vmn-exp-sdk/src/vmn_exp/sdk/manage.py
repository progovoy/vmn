#!/usr/bin/env python3
"""Change stored runs from Python: archive them, tag them, and — from an
orchestrator outside the run's pod — finish them or log to them.

::

    from vmn_exp.sdk import manage

    manage.archive_run("my_app", "@3")
    manage.set_tags("my_app", "latest", {"verdict": "keep"}, remove=["todo"])
    manage.log_note("my_app", run_id, "closed by orchestrator at study end")
    manage.finish_run("my_app", run_id, 1, error="OOMKilled", end_reason="closed")

*ref* takes whatever the CLI takes — a full verstr, a unique prefix, ``@N`` or
``latest`` — and each call returns the verstr it changed, or raises ValueError
when *ref* resolves to no run. Archived runs are hidden by
:func:`vmn_exp.sdk.reader.list_runs` unless ``include_archived=True``.
"""
from vmn_exp.core import run_finish
from vmn_exp.core.manage import set_archived, tag_run
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.run_finish import FinishRefusedError  # noqa: F401
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log
from vmn_exp.sdk.reader import _resolve


def _target(app_name, ref, storage):
    app_name, storage, _ = _resolve(app_name, storage)
    verstr, err = resolve_experiment(storage, app_name, ref or "latest")
    if err:
        raise ValueError(err)
    return app_name, storage, verstr


def _changed(done, app_name, verstr):
    if not done:
        raise ValueError(f"Experiment '{verstr}' not found for {app_name}")
    return verstr


def archive_run(app_name=None, ref="latest", *, storage=None):
    """Archive a run: it stays stored, but listings hide it by default."""
    app_name, storage, verstr = _target(app_name, ref, storage)
    return _changed(set_archived(storage, app_name, verstr, True), app_name, verstr)


def unarchive_run(app_name=None, ref="latest", *, storage=None):
    app_name, storage, verstr = _target(app_name, ref, storage)
    return _changed(set_archived(storage, app_name, verstr, False), app_name, verstr)


def set_tags(app_name=None, ref="latest", tags=None, *, remove=None, storage=None):
    """Set *tags* (``{key: value}``, stored as strings) and drop *remove* keys."""
    app_name, storage, verstr = _target(app_name, ref, storage)
    done = tag_run(storage, app_name, verstr, tags, remove)
    return _changed(done, app_name, verstr)


def finish_run(app_name, ref, exit_code, *, error=None, end_reason=None, force=False,
               storage=None):
    """Write the run's final state without reopening it: no heartbeat, no
    ``running`` first. *error* (a message or an exception) and *end_reason*
    are recorded like ``run.finish``'s.

    Raises :class:`FinishRefusedError` while another attempt still heartbeats
    the run (fresh by its clock or the store's) or once it has finished,
    unless *force*: that attempt's later heartbeats are then dropped.
    """
    app_name, storage, verstr = _target(app_name, ref, storage)
    done = run_finish.finish_run(storage, app_name, verstr, exit_code, error=error,
                                 end_reason=end_reason, force=force)
    return _changed(done, app_name, verstr)


def log_note(app_name, ref, text, *, storage=None):
    """Append a note under this process's own stream; any run, any state."""
    return _append(app_name, ref, storage, create_log_entry("note", text=str(text)))


def log_metrics(app_name, ref, values, *, step=None, storage=None):
    """Append *values* (``{name: number}``) as one metrics entry, at *step*
    when given (unstepped otherwise, like ``vmn-exp add --metrics``)."""
    entry = create_log_entry("metrics", values=dict(values))
    if step is not None:
        entry["step"] = step
    return _append(app_name, ref, storage, entry)


def _append(app_name, ref, storage, entry):
    app_name, storage, verstr = _target(app_name, ref, storage)
    if not storage.exists(app_name, verstr):
        return _changed(False, app_name, verstr)
    append_to_log(storage, app_name, verstr, entry)
    # A one-shot call: no heartbeat is around to ship it later.
    flush_log(storage, app_name, verstr)
    return verstr
