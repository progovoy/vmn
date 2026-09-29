"""A run that is finishing is still this process's export, never a launcher.

``Run.finish()`` marks the run finished, then flushes its log, publishes the
final state and drains alerts before it unregisters. Through that window
``VMN_EXPERIMENT_ID`` still names the run, so a sibling thread's
``start_run()`` read it as its launcher and nested under a run that was never
its parent (the uiload crowd of concurrent single runs came out parented).
"""
import os
from types import SimpleNamespace

from vmn_exp.sdk import context


def test_a_finishing_run_is_not_taken_for_a_launcher(monkeypatch):
    monkeypatch.delenv(context.EXPERIMENT_ID_ENV, raising=False)
    run = SimpleNamespace(id="sibling", app_name="app", pid=os.getpid(), _finished=False)
    context.register(run)
    try:
        run._finished = True  # finish() under way: not yet unregistered
        assert context.launcher_experiment_id() is None
    finally:
        context.unregister(run)
    assert os.environ.get(context.EXPERIMENT_ID_ENV) is None


def _run(run_id):
    return SimpleNamespace(id=run_id, app_name="app", pid=os.getpid(), _finished=False)


def test_a_run_opened_while_a_sibling_finishes_keeps_the_real_baseline(monkeypatch):
    monkeypatch.delenv(context.EXPERIMENT_ID_ENV, raising=False)
    finishing, opened = _run("finishing"), _run("opened")
    context.register(finishing)
    finishing._finished = True
    context.register(opened)
    try:
        context.unregister(finishing)
        assert context.launcher_experiment_id() is None
    finally:
        context.unregister(opened)
    assert os.environ.get(context.EXPERIMENT_ID_ENV) is None
