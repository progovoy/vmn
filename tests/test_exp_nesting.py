"""Nesting for the in-process SDK: explicit parent > in-process stack > env var."""
import os
import subprocess

import pytest

from version_stamp.core.experiment_tree import INNER, OUTER, annotate_tree
from version_stamp.exp import start_run
from helpers import _PROJECT_ROOT, _PY, _bootstrap, _storage


def _meta(app_layout, verstr):
    meta, _ = _storage(app_layout).load(app_layout.app_name, verstr)
    return meta


def _metas(app_layout):
    return _storage(app_layout).list_snapshots(app_layout.app_name)


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)
    yield
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)


def test_nested_inner_run_parents_to_the_open_outer_run(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="outer") as outer:
        with start_run(app_layout.app_name, note="inner", nested=True) as inner:
            assert inner.id != outer.id

    assert _meta(app_layout, inner.id)["parent"] == outer.id
    assert "parent" not in _meta(app_layout, outer.id)

    rows = annotate_tree(
        [
            {"verstr": m["verstr"], "parent": m.get("parent"), "status": "succeeded"}
            for m in _metas(app_layout)
        ]
    )
    by_verstr = {r["verstr"]: r for r in rows}
    assert by_verstr[outer.id]["kind"] == OUTER
    assert by_verstr[inner.id]["kind"] == INNER
    assert by_verstr[inner.id]["depth"] == 1


def test_nesting_uses_the_innermost_open_run(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as a:
        with start_run(app_layout.app_name, nested=True) as b:
            with start_run(app_layout.app_name, nested=True) as c:
                pass

    assert _meta(app_layout, b.id)["parent"] == a.id
    assert _meta(app_layout, c.id)["parent"] == b.id


def test_nested_without_an_open_run_records_no_parent(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, nested=True) as run:
        pass

    assert "parent" not in _meta(app_layout, run.id)


def test_explicit_parent_wins_over_the_in_process_stack(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="first") as first:
        pass

    with start_run(app_layout.app_name, note="outer") as outer:
        with start_run(
            app_layout.app_name, nested=True, parent=first.id
        ) as inner:
            pass

    assert _meta(app_layout, inner.id)["parent"] == first.id


def test_unresolvable_explicit_parent_raises(app_layout):
    _bootstrap(app_layout)

    with pytest.raises(ValueError):
        start_run(app_layout.app_name, parent="0.0.1-dev.deadbeef.deadbeef")

    assert not _metas(app_layout), "no experiment record may be left behind"


def test_stale_env_experiment_id_is_warned_and_ignored(app_layout):
    _bootstrap(app_layout)

    os.environ["VMN_EXPERIMENT_ID"] = "0.0.1-dev.deadbeef.deadbeef"
    with start_run(app_layout.app_name) as run:
        pass

    assert "parent" not in _meta(app_layout, run.id)


def test_env_experiment_id_becomes_the_parent(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="outer") as outer:
        pass

    os.environ["VMN_EXPERIMENT_ID"] = outer.id
    with start_run(app_layout.app_name, note="inner") as inner:
        pass

    assert _meta(app_layout, inner.id)["parent"] == outer.id


def test_a_run_never_becomes_its_own_parent(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name) as run:
        # Mid-run the env points at this very run. Opening another run under
        # it is only supported explicitly (nested=True, see
        # test_reentry_on_the_same_thread_without_nesting_is_rejected for the
        # bare re-entry case) — but the run itself must never gain a parent
        # from its own self-referencing export either way.
        assert os.environ["VMN_EXPERIMENT_ID"] == run.id
        with start_run(app_layout.app_name, nested=True) as inner:
            pass

    assert "parent" not in _meta(app_layout, run.id)
    assert _meta(app_layout, inner.id)["parent"] == run.id


def test_reentry_on_the_same_thread_without_nesting_is_rejected(app_layout):
    """Re-running a notebook cell that never called ``run.finish()`` must not
    silently chain the new run under the stale still-open one."""
    _bootstrap(app_layout)

    run = start_run(app_layout.app_name)
    try:
        with pytest.raises(RuntimeError, match="already active"):
            start_run(app_layout.app_name)
    finally:
        run.finish()

    # the rejected call left no experiment record behind
    assert [m["verstr"] for m in _metas(app_layout)] == [run.id]


def test_reentry_is_allowed_again_once_the_open_run_finishes(app_layout):
    _bootstrap(app_layout)

    first = start_run(app_layout.app_name)
    first.finish()

    with start_run(app_layout.app_name) as second:
        pass

    assert second.id != first.id
    assert "parent" not in _meta(app_layout, second.id)


def test_env_is_exported_while_open_and_restored_on_finish(app_layout):
    _bootstrap(app_layout)

    os.environ["VMN_EXPERIMENT_ID"] = "previous-value"
    with start_run(app_layout.app_name) as run:
        assert os.environ["VMN_EXPERIMENT_ID"] == run.id
        assert os.environ["VMN_APP_NAME"] == app_layout.app_name
    assert os.environ["VMN_EXPERIMENT_ID"] == "previous-value"

    os.environ.pop("VMN_EXPERIMENT_ID", None)
    os.environ.pop("VMN_APP_NAME", None)
    with start_run(app_layout.app_name) as run:
        assert os.environ["VMN_EXPERIMENT_ID"] == run.id
    assert "VMN_EXPERIMENT_ID" not in os.environ
    assert "VMN_APP_NAME" not in os.environ


def test_stale_env_warning_survives_a_bare_python_process(app_layout):
    """Warning about a pruned parent goes through VMN_LOGGER, which raises
    until the CLI initializes it — and an SDK user never runs the CLI."""
    _bootstrap(app_layout)

    env = dict(os.environ)
    env["VMN_WORKING_DIR"] = app_layout.repo_path
    env["PYTHONPATH"] = _PROJECT_ROOT
    env["VMN_EXPERIMENT_ID"] = "0.0.1-dev.deadbeef.deadbeef"
    proc = subprocess.run(
        [
            _PY,
            "-c",
            "from version_stamp.exp import start_run\n"
            "with start_run(%r) as run:\n"
            "    pass\n"
            "print(run.id)\n" % app_layout.app_name,
        ],
        cwd=app_layout.repo_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "AttributeError" not in proc.stderr, proc.stderr

    verstr = proc.stdout.strip().splitlines()[-1]
    assert "parent" not in _meta(app_layout, verstr)


def test_subprocess_vmn_exp_run_auto_links_as_an_inner_run(app_layout):
    _bootstrap(app_layout)

    with start_run(app_layout.app_name, note="sdk outer") as outer:
        # Nothing is passed explicitly: the child inherits the env the open run
        # exported, exactly as a training script's subprocess would.
        child_env = dict(os.environ)
        child_env["VMN_WORKING_DIR"] = app_layout.repo_path
        child_env["PYTHONPATH"] = _PROJECT_ROOT
        proc = subprocess.run(
            [
                _PY,
                "-m",
                "version_stamp.cli.entry",
                "exp",
                "run",
                app_layout.app_name,
                "--",
                _PY,
                "-c",
                "print('trial')",
            ],
            cwd=app_layout.repo_path,
            env=child_env,
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0, proc.stderr

    children = [m["verstr"] for m in _metas(app_layout) if m.get("parent") == outer.id]
    assert len(children) == 1, [m["verstr"] for m in _metas(app_layout)]
