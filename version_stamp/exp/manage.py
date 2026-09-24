#!/usr/bin/env python3
"""Change stored runs from Python: archive them, tag them.

::

    from version_stamp.exp import manage

    manage.archive_run("my_app", "@3")
    manage.set_tags("my_app", "latest", {"verdict": "keep"}, remove=["todo"])

*ref* takes whatever the CLI takes — a full verstr, a unique prefix, ``@N`` or
``latest`` — and each call returns the verstr it changed, or raises ValueError
when *ref* resolves to no run. Archived runs are hidden by
:func:`version_stamp.exp.reader.list_runs` unless ``include_archived=True``.
"""
from version_stamp.core.experiment_manage import set_archived, tag_run
from version_stamp.core.experiment_refs import resolve_experiment
from version_stamp.exp.reader import _resolve


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
