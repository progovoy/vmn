#!/usr/bin/env python3
"""Change stored runs from Python: archive them, tag them, and — from an
orchestrator outside the run's pod — finish them or log to them.

::

    from vmn_exp.sdk import manage

    manage.archive_run("my_app", "@3")
    manage.archive_runs("my_app", 'tags.batch = "old"')
    manage.set_tags("my_app", "latest", {"verdict": "keep"}, remove=["todo"])
    manage.log_note("my_app", run_id, "closed by orchestrator at study end")
    manage.finish_run("my_app", run_id, 1, error="OOMKilled", end_reason="closed")

*ref* takes whatever the CLI takes — a full verstr, a unique prefix, ``@N`` or
``latest`` — and each call returns the verstr it changed, or raises ValueError
when *ref* resolves to no run. :func:`archive_runs`/:func:`unarchive_runs`
take a query instead and return every verstr they changed. Archived runs are hidden by
:func:`vmn_exp.sdk.reader.list_runs` unless ``include_archived=True``.
"""
from vmn_exp.core import run_finish
from vmn_exp.core.manage import set_archived, tag_run
from vmn_exp.core.query import compile_query
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.core.run_finish import FinishRefusedError  # noqa: F401
from vmn_exp.core.writer import append_to_log, create_log_entry, flush_log
from vmn_exp.sdk.reader import _resolve, list_runs
from vmn_exp.storage.s3_base import parallel_map


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


def archive_runs(app_name=None, query=None, *, status=None, storage=None, dry_run=False):
    """Archive every unarchived run *query* (and *status*) selects, like
    ``list_runs(query=, status=)``; the verstrs archived (with *dry_run*,
    the ones that would be). Raises ``QueryError`` on an empty or bad query.
    """
    return _set_archived_by_query(app_name, query, status, storage, dry_run, True)


def unarchive_runs(app_name=None, query=None, *, status=None, storage=None, dry_run=False):
    """Unarchive every archived run *query* (and *status*) selects."""
    return _set_archived_by_query(app_name, query, status, storage, dry_run, False)


def _set_archived_by_query(app_name, query, status, storage, dry_run, archived):
    compile_query(query or "")  # an empty query must not select every run
    app_name, storage, _ = _resolve(app_name, storage)
    rows = list_runs(app_name, storage=storage, query=query, status=status,
                     include_archived=True)
    verstrs = [r["verstr"] for r in rows if bool(r.get("archived")) != archived]
    if dry_run:
        return verstrs
    done = parallel_map(lambda v: set_archived(storage, app_name, v, archived), verstrs)
    # A run deleted since the listing is not counted.
    return [v for v, ok in zip(verstrs, done) if ok]


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
